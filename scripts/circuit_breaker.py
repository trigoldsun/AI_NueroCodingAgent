"""
Circuit Breaker Implementation — Resilience4j-style for Python.

Implements the circuit breaker pattern with CLOSED/OPEN/HALF_OPEN states.
Thread-safe implementation using threading locks.

Configuration options (Resilience4j-style defaults):
    - sliding_window_size: Number of calls to consider for failure rate (default: 10)
    - failure_rate_threshold: Percentage above which circuit opens (default: 50)
    - wait_duration_open: Seconds to wait before transitioning OPEN -> HALF_OPEN (default: 30)
    - permitted_calls_in_half_open: Number of calls allowed in HALF_OPEN state (default: 3)

Example usage:
    @circuit_breaker("my_service")
    def unreliable_function():
        return api.call()

    # With fallback
    @circuit_breaker("my_service", fallback=lambda e: default_value)
    def unreliable_function():
        return api.call()
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Generic, TypeVar

__all__ = ["CircuitBreaker", "CircuitBreakerError", "circuit_breaker", "CircuitState"]

logger = logging.getLogger(__name__)

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])


class CircuitState(Enum):
    """Possible states for a circuit breaker."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerError(Exception):
    """Raised when a call is rejected due to an open circuit."""

    def __init__(self, circuit_name: str, state: CircuitState, message: str | None = None):
        self.circuit_name = circuit_name
        self.state = state
        if message is None:
            message = f"Circuit '{circuit_name}' is {state.value}"
        super().__init__(message)


@dataclass
class CircuitBreakerConfig:
    """
    Configuration for a CircuitBreaker instance.

    Attributes:
        sliding_window_size: Number of recent calls to store for failure tracking.
            Must be at least 1. Default: 10.
        failure_rate_threshold: Failure rate percentage threshold (0-100) that triggers
            opening the circuit. Default: 50.
        wait_duration_open: Seconds to wait in OPEN state before attempting recovery
            (transitioning to HALF_OPEN). Default: 30.
        permitted_calls_in_half_open: Maximum calls allowed in HALF_OPEN state before
            evaluating recovery. Circuit will transition to CLOSED on success or back
            to OPEN on failure. Default: 3.
        minimum_number_of_calls: Minimum calls required in the sliding window before
            failure rate is evaluated. Default: 10.
    """

    sliding_window_size: int = 10
    failure_rate_threshold: float = 50.0
    wait_duration_open: float = 30.0
    permitted_calls_in_half_open: int = 3
    minimum_number_of_calls: int = 10

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.sliding_window_size < 1:
            raise ValueError("sliding_window_size must be at least 1")
        if not 0 <= self.failure_rate_threshold <= 100:
            raise ValueError("failure_rate_threshold must be between 0 and 100")
        if self.wait_duration_open <= 0:
            raise ValueError("wait_duration_open must be positive")
        if self.permitted_calls_in_half_open < 1:
            raise ValueError("permitted_calls_in_half_open must be at least 1")
        if self.minimum_number_of_calls < 1:
            raise ValueError("minimum_number_of_calls must be at least 1")


@dataclass
class CallResult:
    """Records the result of a single call for sliding window tracking."""

    timestamp: float
    is_success: bool
    error: Exception | None = None

    @property
    def is_failure(self) -> bool:
        return not self.is_success


@dataclass
class CircuitBreakerStats:
    """Statistics for a CircuitBreaker instance."""

    circuit_name: str
    state: CircuitState
    calls_in_half_open: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_calls: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None

    @property
    def failure_rate(self) -> float:
        """Calculate current failure rate as a percentage (0-100)."""
        if self.total_calls == 0:
            return 0.0
        return (self.failed_calls / self.total_calls) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "circuit_name": self.circuit_name,
            "state": self.state.value,
            "calls_in_half_open": self.calls_in_half_open,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "total_calls": self.total_calls,
            "failure_rate": round(self.failure_rate, 2),
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
        }


class CircuitBreaker(Generic[T]):
    """
    A thread-safe circuit breaker implementation.

    The circuit breaker monitors calls and tracks failures. When the failure rate
    exceeds the configured threshold, the circuit "opens" and rejects calls.
    After a wait period, it enters HALF_OPEN state to test recovery.

    State transitions:
        CLOSED -> OPEN: When failure rate exceeds threshold in sliding window
        OPEN -> HALF_OPEN: After wait_duration_open seconds elapse
        HALF_OPEN -> CLOSED: When permitted calls succeed
        HALF_OPEN -> OPEN: When a call fails in HALF_OPEN state

    Thread-safety is achieved using a reentrant lock for all state transitions
    and call recording operations.

    Example:
        breaker = CircuitBreaker(
            name="payment_service",
            config=CircuitBreakerConfig(
                sliding_window_size=10,
                failure_rate_threshold=50.0,
                wait_duration_open=30.0,
                permitted_calls_in_half_open=3,
            )
        )

        with breaker:
            result = payment_api.charge(customer_id, amount)
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
        fallback: Callable[[Exception], T] | None = None,
    ) -> None:
        """
        Initialize a CircuitBreaker.

        Args:
            name: Unique identifier for this circuit breaker.
            config: Configuration settings. Uses defaults if not provided.
            fallback: Optional callable invoked when a call fails or is rejected.
                Receives the exception as its only argument.
        """
        if not name or not name.strip():
            raise ValueError("Circuit breaker name cannot be empty")

        self._name = name
        self._config = config or CircuitBreakerConfig()
        self._fallback = fallback

        # Internal state
        self._state = CircuitState.CLOSED
        self._lock = threading.RLock()
        self._calls_window: list[CallResult] = []
        self._opened_at: float | None = None
        self._half_open_calls: int = 0
        self._half_open_successes: int = 0

        # Statistics
        self._stats = CircuitBreakerStats(circuit_name=name, state=CircuitState.CLOSED)

    @property
    def name(self) -> str:
        """The unique name of this circuit breaker."""
        return self._name

    @property
    def state(self) -> CircuitState:
        """Current state of the circuit breaker."""
        with self._lock:
            return self._state

    @property
    def config(self) -> CircuitBreakerConfig:
        """Configuration settings for this circuit breaker."""
        return self._config

    @property
    def stats(self) -> CircuitBreakerStats:
        """Current statistics for this circuit breaker."""
        with self._lock:
            return CircuitBreakerStats(
                circuit_name=self._stats.circuit_name,
                state=self._stats.state,
                calls_in_half_open=self._stats.calls_in_half_open,
                successful_calls=self._stats.successful_calls,
                failed_calls=self._stats.failed_calls,
                total_calls=self._stats.total_calls,
                last_failure_time=self._stats.last_failure_time,
                last_success_time=self._stats.last_success_time,
            )

    def __enter__(self) -> CircuitBreaker[T]:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        pass  # State is managed per-call, not per-context

    def _is_state_transition_needed(self) -> tuple[bool, CircuitState]:
        """
        Check if state transition is needed based on current window.

        Returns:
            Tuple of (needs_transition, target_state). If no transition needed,
            target_state will be current state.
        """
        if self._state == CircuitState.OPEN:
            if self._opened_at is None:
                return True, CircuitState.HALF_OPEN

            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self._config.wait_duration_open:
                return True, CircuitState.HALF_OPEN
            return False, CircuitState.OPEN

        if self._state == CircuitState.HALF_OPEN:
            if self._half_open_calls >= self._config.permitted_calls_in_half_open:
                if self._half_open_successes >= self._config.permitted_calls_in_half_open:
                    return True, CircuitState.CLOSED
                return True, CircuitState.OPEN
            return False, CircuitState.HALF_OPEN

        if self._state == CircuitState.CLOSED:
            if len(self._calls_window) >= self._config.minimum_number_of_calls:
                failure_count = sum(1 for c in self._calls_window if c.is_failure)
                failure_rate = (failure_count / len(self._calls_window)) * 100
                if failure_rate >= self._config.failure_rate_threshold:
                    return True, CircuitState.OPEN

        return False, self._state

    def _transition_to(self, new_state: CircuitState) -> None:
        """Perform state transition with logging and reset of transient state."""
        if new_state == self._state:
            return

        old_state = self._state
        self._state = new_state
        self._stats.state = new_state

        logger.info(
            "Circuit '%s' state transition: %s -> %s",
            self._name,
            old_state.value,
            new_state.value,
        )

        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._half_open_successes = 0
        elif new_state == CircuitState.CLOSED:
            self._calls_window.clear()
            self._half_open_calls = 0
            self._half_open_successes = 0
            self._opened_at = None
        elif new_state == CircuitState.OPEN:
            self._opened_at = time.monotonic()

    def _record_call(self, is_success: bool, error: Exception | None = None) -> None:
        """Record a call result in the sliding window and update statistics."""
        timestamp = time.monotonic()
        call_result = CallResult(timestamp=timestamp, is_success=is_success, error=error)
        self._calls_window.append(call_result)

        if len(self._calls_window) > self._config.sliding_window_size:
            self._calls_window.pop(0)

        self._stats.total_calls += 1
        if is_success:
            self._stats.successful_calls += 1
            self._stats.last_success_time = timestamp
        else:
            self._stats.failed_calls += 1
            self._stats.last_failure_time = timestamp

    def _evaluate_transition(self) -> None:
        """Evaluate and perform any needed state transition."""
        needs_transition, target_state = self._is_state_transition_needed()
        if needs_transition:
            self._transition_to(target_state)

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Execute a function through the circuit breaker.

        Args:
            func: The function to execute.
            *args: Positional arguments to pass to the function.
            **kwargs: Keyword arguments to pass to the function.

        Returns:
            The return value of the function.

        Raises:
            CircuitBreakerError: If the circuit is OPEN and the call is rejected.
            Exception: Any exception raised by the wrapped function.
        """
        with self._lock:
            self._evaluate_transition()

            if self._state == CircuitState.OPEN:
                raise CircuitBreakerError(
                    self._name,
                    self._state,
                    f"Circuit '{self._name}' is OPEN — call rejected",
                )

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self._config.permitted_calls_in_half_open:
                    raise CircuitBreakerError(
                        self._name,
                        self._state,
                        f"Circuit '{self._name}' HALF_OPEN quota exhausted — call rejected",
                    )
                # Increment BEFORE releasing lock — ensures atomic check-and-increment
                self._half_open_calls += 1
                self._stats.calls_in_half_open += 1

        # Execute function OUTSIDE the lock — lock only protects state transitions
        try:
            result = func(*args, **kwargs)
            with self._lock:
                self._record_call(is_success=True)
                if self._state == CircuitState.HALF_OPEN:
                    self._half_open_successes += 1
                self._evaluate_transition()
            return result

        except Exception as e:
            with self._lock:
                self._record_call(is_success=False, error=e)
                if self._state == CircuitState.HALF_OPEN:
                    self._transition_to(CircuitState.OPEN)
                else:
                    self._evaluate_transition()

            if self._fallback is not None:
                logger.debug(
                    "Circuit '%s' call failed, invoking fallback: %s",
                    self._name,
                    str(e),
                )
                return self._fallback(e)

            raise

    def reset(self) -> None:
        """
        Manually reset the circuit breaker to CLOSED state.

        Clears the call history and resets all statistics.
        """
        with self._lock:
            self._calls_window.clear()
            self._opened_at = None
            self._half_open_calls = 0
            self._half_open_successes = 0
            self._transition_to(CircuitState.CLOSED)
            self._stats = CircuitBreakerStats(
                circuit_name=self._name, state=CircuitState.CLOSED
            )
            logger.info("Circuit '%s' manually reset to CLOSED", self._name)


_CIRCUIT_BREAKER_REGISTRY: dict[str, CircuitBreaker[Any]] = {}
_REGISTRY_LOCK = threading.Lock()


def _get_or_create_breaker(
    name: str,
    config: CircuitBreakerConfig | None,
) -> CircuitBreaker[Any]:
    """Get an existing circuit breaker from registry or create a new one."""
    with _REGISTRY_LOCK:
        if name in _CIRCUIT_BREAKER_REGISTRY:
            return _CIRCUIT_BREAKER_REGISTRY[name]

        breaker = CircuitBreaker(name=name, config=config)
        _CIRCUIT_BREAKER_REGISTRY[name] = breaker
        return breaker


def circuit_breaker(
    name: str,
    config: CircuitBreakerConfig | None = None,
    *,
    fallback: Callable[[Exception], Any] | None = None,
    registry: bool = True,
) -> Callable[[F], F]:
    """
    Decorator to wrap a function with a circuit breaker.

    Args:
        name: Unique identifier for the circuit breaker. If registry=True and a
            breaker with this name already exists, the existing instance is reused.
        config: Circuit breaker configuration. Uses defaults if not provided.
        fallback: Optional fallback function called when the call fails or is rejected.
            Receives the exception as its argument and should return a value to use
            as a substitute return value.
        registry: If True, store breaker in global registry for reuse across multiple
            decorated functions with the same name. Default: True.

    Returns:
        A decorator function that wraps the target with the circuit breaker.

    Example:
        @circuit_breaker("external_api", fallback=lambda e: None)
        def call_external_api():
            return requests.get("https://api.example.com/data")

        # Equivalent using explicit config
        config = CircuitBreakerConfig(
            sliding_window_size=20,
            failure_rate_threshold=60.0,
            wait_duration_open=60.0,
        )
        @circuit_breaker("critical_service", config=config)
        def critical_operation():
            return service.process()
    """
    breaker = _get_or_create_breaker(name, config)
    if fallback is not None:
        breaker._fallback = fallback

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return breaker.call(func, *args, **kwargs)

        wrapper._circuit_breaker = breaker  # type: ignore[attr-defined]
        wrapper._fallback = fallback  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator


def get_circuit_breaker(name: str) -> CircuitBreaker[Any] | None:
    """
    Retrieve a circuit breaker from the global registry.

    Args:
        name: The name of the circuit breaker to retrieve.

    Returns:
        The CircuitBreaker instance if found, None otherwise.
    """
    with _REGISTRY_LOCK:
        return _CIRCUIT_BREAKER_REGISTRY.get(name)


def reset_all_circuit_breakers() -> None:
    """Reset all circuit breakers in the global registry to CLOSED state."""
    with _REGISTRY_LOCK:
        for breaker in _CIRCUIT_BREAKER_REGISTRY.values():
            breaker.reset()


if __name__ == "__main__":
    import random

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    @circuit_breaker(
        "demo_service",
        config=CircuitBreakerConfig(
            sliding_window_size=10,
            failure_rate_threshold=50.0,
            wait_duration_open=5.0,
            permitted_calls_in_half_open=3,
        ),
        fallback=lambda e: "fallback_result",
    )
    def unreliable_operation(item: str) -> str:
        """Demo function that fails randomly."""
        if random.random() < 0.6:
            raise ConnectionError(f"Simulated failure for {item}")
        return f"success:{item}"

    print("Running circuit breaker demo...")
    print("=" * 60)

    for i in range(1, 21):
        result = unreliable_operation(f"item_{i}")
        print(f"Call {i}: {result}")

        breaker = get_circuit_breaker("demo_service")
        if breaker:
            stats = breaker.stats
            print(f"  State: {stats.state.value}, Success: {stats.successful_calls}, Failed: {stats.failed_calls}")

        time.sleep(0.2)

    print("=" * 60)
    breaker = get_circuit_breaker("demo_service")
    if breaker:
        print(f"\nFinal circuit breaker state: {breaker.state.value}")
        print(f"Final statistics: {breaker.stats.to_dict()}")
