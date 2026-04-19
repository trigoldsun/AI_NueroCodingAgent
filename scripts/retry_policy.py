"""
Retry policy with exponential backoff and jitter.

Resilience4j-style implementation providing:
- Configurable max attempts, wait duration, and backoff multiplier
- Exponential backoff with optional jitter
- Exception filtering via predicate
- Thread-safe retry operations
"""

from __future__ import annotations

import functools
import random
import time
import threading
from dataclasses import dataclass, field
from typing import Callable, Set, Type, TypeVar, Union, overload

T = TypeVar("T")
TFunc = TypeVar("TFunc", bound=Callable[..., object])


@dataclass
class RetryConfig:
    """
    Configuration for retry behavior.

    Attributes:
        max_attempts: Maximum number of retry attempts (including the initial call).
        wait_duration_ms: Initial wait duration in milliseconds between retries.
        exponential_backoff_multiplier: Multiplier for exponential backoff calculation.
        jitter: Whether to add random jitter to wait durations.
        jitter_max_ms: Maximum additional jitter in milliseconds (only used when jitter=True).
        retryable_exceptions: Set of exception types that trigger retries. If None, all exceptions are retried.

    Example:
        >>> config = RetryConfig(
        ...     max_attempts=3,
        ...     wait_duration_ms=500,
        ...     exponential_backoff_multiplier=2.0,
        ...     jitter=True,
        ...     jitter_max_ms=100,
        ... )
    """

    max_attempts: int = 3
    wait_duration_ms: int = 500
    exponential_backoff_multiplier: float = 2.0
    jitter: bool = True
    jitter_max_ms: int = 100
    retryable_exceptions: Set[Type[Exception]] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.wait_duration_ms < 0:
            raise ValueError("wait_duration_ms must be non-negative")
        if self.exponential_backoff_multiplier <= 0:
            raise ValueError("exponential_backoff_multiplier must be positive")
        if self.jitter_max_ms < 0:
            raise ValueError("jitter_max_ms must be non-negative")


class RetryContext:
    """
    Context object passed to retry callbacks containing attempt information.

    Attributes:
        attempt: Current attempt number (1-based, where 1 is the first attempt).
        total_attempts: Maximum number of attempts configured.
        last_exception: The exception from the last attempt, if any.
    """

    __slots__ = ("attempt", "total_attempts", "last_exception")

    def __init__(
        self,
        attempt: int,
        total_attempts: int,
        last_exception: Exception | None,
    ) -> None:
        self.attempt = attempt
        self.total_attempts = total_attempts
        self.last_exception = last_exception


class RetryExhausted(Exception):
    """
    Raised when all retry attempts have been exhausted.

    Attributes:
        config: The retry configuration that was used.
        last_exception: The exception from the final attempt.
    """

    def __init__(
        self,
        config: RetryConfig,
        last_exception: Exception,
    ) -> None:
        self.config = config
        self.last_exception = last_exception
        super().__init__(
            f"All {config.max_attempts} attempts failed. "
            f"Last exception: {last_exception!r}"
        )


def _calculate_wait_duration(
    config: RetryConfig,
    attempt: int,
    lock: threading.Lock,
) -> float:
    """
    Calculate the wait duration for a given attempt using exponential backoff and optional jitter.

    Args:
        config: The retry configuration.
        attempt: The current attempt number (1-based).
        lock: Thread lock for thread-safe random number generation.

    Returns:
        Wait duration in seconds.
    """
    # Exponential backoff: wait_duration * (multiplier ^ (attempt - 1))
    # Attempt 1: 500ms, Attempt 2: 1000ms, Attempt 3: 2000ms, etc.
    wait_ms = config.wait_duration_ms * (config.exponential_backoff_multiplier ** (attempt - 1))

    if config.jitter:
        with lock:
            jitter_ms = random.randint(0, config.jitter_max_ms)
        wait_ms += jitter_ms

    return wait_ms / 1000.0


def _is_retryable(
    config: RetryConfig,
    exception: Exception,
) -> bool:
    """
    Determine if an exception is retryable based on the configuration.

    Args:
        config: The retry configuration.
        exception: The exception to check.

    Returns:
        True if the exception should trigger a retry, False otherwise.
    """
    if not config.retryable_exceptions:
        # No exceptions specified means all are retryable
        return True

    return isinstance(exception, tuple(config.retryable_exceptions))


@overload
def retry(
    func: TFunc,
    /,
) -> TFunc: ...


@overload
def retry(
    func: None = None,
    *,
    max_attempts: int = ...,
    wait_duration_ms: int = ...,
    exponential_backoff_multiplier: float = ...,
    jitter: bool = ...,
    jitter_max_ms: int = ...,
    retryable_exceptions: Set[Type[Exception]] = ...,
) -> Callable[[TFunc], TFunc]: ...


def retry(
    func: TFunc | None = None,
    /,
    *,
    max_attempts: int = 3,
    wait_duration_ms: int = 500,
    exponential_backoff_multiplier: float = 2.0,
    jitter: bool = True,
    jitter_max_ms: int = 100,
    retryable_exceptions: Set[Type[Exception]] | None = None,
) -> Union[TFunc, Callable[[TFunc], TFunc]]:
    """
    Decorator that retries a function with exponential backoff and jitter.

    Resembles Resilience4j's Retry.of_default_config() and @Retry annotation.

    Args:
        func: The function to decorate (when used without parentheses).
        max_attempts: Maximum number of attempts (default: 3).
        wait_duration_ms: Initial wait duration in milliseconds (default: 500).
        exponential_backoff_multiplier: Multiplier for exponential backoff (default: 2.0).
        jitter: Whether to add random jitter (default: True).
        jitter_max_ms: Maximum jitter in milliseconds (default: 100).
        retryable_exceptions: Set of exception types to retry. If None, all are retried.

    Returns:
        Decorated function with retry semantics.

    Example:
        Basic usage:
        >>> @retry
        ... def unreliable_call():
        ...     return might_fail()

        Custom configuration:
        >>> @retry(max_attempts=5, wait_duration_ms=1000, jitter=False)
        ... def another_call():
        ...     return might_fail()

        Specific exceptions only:
        >>> @retry(retryable_exceptions={ConnectionError, TimeoutError})
        ... def network_call():
        ...     return fetch_data()
    """

    def decorator(fn: TFunc) -> TFunc:
        # Thread-safe lock for jitter random generation (created once per decorated function)
        lock = threading.Lock()

        # RetryConfig created once at decoration time, not per-call
        config = RetryConfig(
            max_attempts=max_attempts,
            wait_duration_ms=wait_duration_ms,
            exponential_backoff_multiplier=exponential_backoff_multiplier,
            jitter=jitter,
            jitter_max_ms=jitter_max_ms,
            retryable_exceptions=retryable_exceptions or set(),
        )

        @functools.wraps(fn)
        def wrapper(*args: object, **kwargs: object) -> object:
            last_exception: Exception | None = None

            for attempt in range(1, config.max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    last_exception = exc

                    # Check if this is the last attempt
                    if attempt >= config.max_attempts:
                        break

                    # Check if exception is retryable
                    if not _is_retryable(config, exc):
                        raise

                    # Calculate and apply wait duration
                    wait_seconds = _calculate_wait_duration(config, attempt, lock)
                    time.sleep(wait_seconds)

            # All attempts exhausted
            if last_exception is not None:
                raise RetryExhausted(config, last_exception) from last_exception

            # Should not reach here, but satisfy type checker
            raise RuntimeError("Retry exhausted without exception")

        return wrapper  # type: ignore[return-value]

    # Support both @retry and @retry() syntax
    if func is not None:
        return decorator(func)

    return decorator


# Convenience function for creating pre-configured retry policies
def create_retry_policy(
    max_attempts: int = 3,
    wait_duration_ms: int = 500,
    exponential_backoff_multiplier: float = 2.0,
    jitter: bool = True,
    jitter_max_ms: int = 100,
    retryable_exceptions: Set[Type[Exception]] | None = None,
) -> Callable[[TFunc], TFunc]:
    """
    Create a pre-configured retry decorator.

    This is useful when you want to reuse the same retry configuration
    across multiple functions without repeating parameters.

    Args:
        max_attempts: Maximum number of attempts (default: 3).
        wait_duration_ms: Initial wait duration in milliseconds (default: 500).
        exponential_backoff_multiplier: Multiplier for exponential backoff (default: 2.0).
        jitter: Whether to add random jitter (default: True).
        jitter_max_ms: Maximum jitter in milliseconds (default: 100).
        retryable_exceptions: Set of exception types to retry. If None, all are retried.

    Returns:
        A configured retry decorator.

    Example:
        >>> # Create a policy once
        >>> aggressive_retry = create_retry_policy(
        ...     max_attempts=5,
        ...     wait_duration_ms=200,
        ...     jitter_max_ms=50,
        ... )
        >>>
        >>> # Reuse across multiple functions
        >>> @aggressive_retry
        ... def call_service_a(): ...
        >>>
        >>> @aggressive_retry
        ... def call_service_b(): ...
    """
    return retry(
        max_attempts=max_attempts,
        wait_duration_ms=wait_duration_ms,
        exponential_backoff_multiplier=exponential_backoff_multiplier,
        jitter=jitter,
        jitter_max_ms=jitter_max_ms,
        retryable_exceptions=retryable_exceptions,
    )


# Default retry policy matching Resilience4j defaults
default_retry_policy = create_retry_policy(
    max_attempts=3,
    wait_duration_ms=500,
    exponential_backoff_multiplier=2.0,
    jitter=True,
    jitter_max_ms=100,
)
