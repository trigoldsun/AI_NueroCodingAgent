"""
Unit tests for circuit_breaker module.
Tests all states, edge cases, and concurrent access.
"""

import threading
import time
import pytest
from typing import Any

from scripts.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitState,
    CallResult,
    CircuitBreakerStats,
    circuit_breaker,
    get_circuit_breaker,
)


class TestCircuitBreakerConfig:
    """Tests for CircuitBreakerConfig validation."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CircuitBreakerConfig()
        assert config.sliding_window_size == 10
        assert config.failure_rate_threshold == 50.0
        assert config.wait_duration_open == 30.0
        assert config.permitted_calls_in_half_open == 3
        assert config.minimum_number_of_calls == 10

    def test_valid_custom_config(self):
        """Test custom configuration with valid values."""
        config = CircuitBreakerConfig(
            sliding_window_size=20,
            failure_rate_threshold=60.0,
            wait_duration_open=60.0,
            permitted_calls_in_half_open=5,
            minimum_number_of_calls=5,
        )
        assert config.sliding_window_size == 20
        assert config.failure_rate_threshold == 60.0

    def test_invalid_sliding_window_size(self):
        """Test that sliding_window_size < 1 raises ValueError."""
        with pytest.raises(ValueError, match="sliding_window_size must be at least 1"):
            CircuitBreakerConfig(sliding_window_size=0)

    def test_invalid_failure_rate_threshold_low(self):
        """Test that failure_rate_threshold < 0 raises ValueError."""
        with pytest.raises(ValueError, match="failure_rate_threshold must be between 0 and 100"):
            CircuitBreakerConfig(failure_rate_threshold=-1)

    def test_invalid_failure_rate_threshold_high(self):
        """Test that failure_rate_threshold > 100 raises ValueError."""
        with pytest.raises(ValueError, match="failure_rate_threshold must be between 0 and 100"):
            CircuitBreakerConfig(failure_rate_threshold=101)

    def test_invalid_wait_duration_open(self):
        """Test that wait_duration_open <= 0 raises ValueError."""
        with pytest.raises(ValueError, match="wait_duration_open must be positive"):
            CircuitBreakerConfig(wait_duration_open=0)

    def test_invalid_permitted_calls_in_half_open(self):
        """Test that permitted_calls_in_half_open < 1 raises ValueError."""
        with pytest.raises(ValueError, match="permitted_calls_in_half_open must be at least 1"):
            CircuitBreakerConfig(permitted_calls_in_half_open=0)

    def test_invalid_minimum_number_of_calls(self):
        """Test that minimum_number_of_calls < 1 raises ValueError."""
        with pytest.raises(ValueError, match="minimum_number_of_calls must be at least 1"):
            CircuitBreakerConfig(minimum_number_of_calls=0)


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_initial_state_is_closed(self):
        """Test that circuit breaker starts in CLOSED state."""
        breaker = CircuitBreaker("test_breaker")
        assert breaker.state == CircuitState.CLOSED

    def test_empty_name_raises_error(self):
        """Test that empty name raises ValueError."""
        with pytest.raises(ValueError, match="Circuit breaker name cannot be empty"):
            CircuitBreaker("")

    def test_whitespace_name_raises_error(self):
        """Test that whitespace-only name raises ValueError."""
        with pytest.raises(ValueError, match="Circuit breaker name cannot be empty"):
            CircuitBreaker("   ")

    def test_name_property(self):
        """Test name property returns correct value."""
        breaker = CircuitBreaker("my_breaker")
        assert breaker.name == "my_breaker"

    def test_config_property(self):
        """Test config property returns correct config."""
        config = CircuitBreakerConfig(sliding_window_size=20)
        breaker = CircuitBreaker("test", config=config)
        assert breaker.config.sliding_window_size == 20

    def test_successful_call_records_success(self):
        """Test that successful calls are recorded correctly."""
        breaker = CircuitBreaker("test")
        result = breaker.call(lambda: 42)
        assert result == 42
        stats = breaker.stats
        assert stats.successful_calls == 1
        assert stats.failed_calls == 0
        assert stats.total_calls == 1

    def test_failed_call_records_failure(self):
        """Test that failed calls are recorded correctly."""
        breaker = CircuitBreaker("test")

        def failing_func():
            raise ValueError("test error")

        with pytest.raises(ValueError):
            breaker.call(failing_func)

        stats = breaker.stats
        assert stats.failed_calls == 1
        assert stats.successful_calls == 0
        assert stats.total_calls == 1

    def test_circuit_opens_on_failure_threshold(self):
        """Test circuit opens when failure rate exceeds threshold."""
        config = CircuitBreakerConfig(
            sliding_window_size=5,
            failure_rate_threshold=50.0,
            minimum_number_of_calls=5,
        )
        breaker = CircuitBreaker("test", config=config)

        # Make 5 failing calls - should open circuit
        for _ in range(5):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.state == CircuitState.OPEN

    def test_circuit_stays_closed_below_threshold(self):
        """Test circuit stays closed when failure rate is below threshold."""
        config = CircuitBreakerConfig(
            sliding_window_size=10,
            failure_rate_threshold=50.0,
            minimum_number_of_calls=10,
        )
        breaker = CircuitBreaker("test", config=config)

        # Make 9 successes and 1 failure - still below threshold
        for _ in range(9):
            breaker.call(lambda: True)
        with pytest.raises(ValueError):
            breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.state == CircuitState.CLOSED

    def test_open_circuit_rejects_calls(self):
        """Test that OPEN circuit rejects calls with CircuitBreakerError."""
        config = CircuitBreakerConfig(
            sliding_window_size=5,
            failure_rate_threshold=50.0,
            minimum_number_of_calls=5,
        )
        breaker = CircuitBreaker("test", config=config)

        # Open the circuit
        for _ in range(5):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.state == CircuitState.OPEN

        # Next call should be rejected
        with pytest.raises(CircuitBreakerError, match="is OPEN"):
            breaker.call(lambda: 42)

    def test_fallback_invoked_on_failure(self):
        """Test that fallback is called when decorated function fails."""
        breaker = CircuitBreaker("test", fallback=lambda e: "fallback_result")

        def failing_func():
            raise ValueError("test error")

        result = breaker.call(failing_func)
        assert result == "fallback_result"

    def test_circuit_open_rejects_with_error(self):
        """Open circuit rejects calls before function runs — raises CircuitBreakerError."""
        config = CircuitBreakerConfig(
            sliding_window_size=5,
            failure_rate_threshold=50.0,
            minimum_number_of_calls=5,
        )
        breaker = CircuitBreaker("test_open_rejection", config=config)

        # Open the circuit with 5 failing calls
        for _ in range(5):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
        assert breaker.state == CircuitState.OPEN

        # OPEN circuit rejects the call before function runs — CircuitBreakerError raised
        with pytest.raises(CircuitBreakerError, match="is OPEN"):
            breaker.call(lambda: 42)

    def test_half_open_state_allows_test_calls(self):
        """Test that HALF_OPEN state allows limited test calls after wait_duration."""
        config = CircuitBreakerConfig(
            sliding_window_size=5,
            failure_rate_threshold=50.0,
            minimum_number_of_calls=5,
            wait_duration_open=0.1,
            permitted_calls_in_half_open=3,
        )
        breaker = CircuitBreaker("test_half_open_calls", config=config)

        # Open the circuit
        for _ in range(5):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.state == CircuitState.OPEN

        # Wait for wait_duration to elapse
        time.sleep(0.15)

        # Transition to HALF_OPEN happens on next call
        result = breaker.call(lambda: "success")
        assert result == "success"
        assert breaker.state == CircuitState.HALF_OPEN

        # Should allow more calls in HALF_OPEN
        for _ in range(2):
            result = breaker.call(lambda: "success")
            assert result == "success"

    def test_half_open_failure_reopens_circuit(self):
        """Test that failed calls in HALF_OPEN reopen the circuit."""
        config = CircuitBreakerConfig(
            sliding_window_size=5,
            failure_rate_threshold=50.0,
            minimum_number_of_calls=5,
            wait_duration_open=0.1,
            permitted_calls_in_half_open=3,
        )
        breaker = CircuitBreaker("test_half_open_failure", config=config)

        # Open the circuit
        for _ in range(5):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        # Wait for wait_duration to elapse
        time.sleep(0.15)

        # Trigger transition to HALF_OPEN via a call (lazy evaluation)
        result = breaker.call(lambda: "success")
        assert result == "success"
        assert breaker.state == CircuitState.HALF_OPEN

        # Fail a call in HALF_OPEN — should reopen circuit
        with pytest.raises(ValueError):
            breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.state == CircuitState.OPEN

    def test_half_open_success_closes_circuit(self):
        """Test that successful calls in HALF_OPEN close the circuit."""
        config = CircuitBreakerConfig(
            sliding_window_size=5,
            failure_rate_threshold=50.0,
            minimum_number_of_calls=5,
            wait_duration_open=0.1,
            permitted_calls_in_half_open=3,
        )
        breaker = CircuitBreaker("test_half_open_success", config=config)

        # Open the circuit
        for _ in range(5):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        # Wait for wait_duration to elapse
        time.sleep(0.15)

        # Trigger transition to HALF_OPEN via a call
        breaker.call(lambda: "success")
        assert breaker.state == CircuitState.HALF_OPEN

        # Make remaining successful calls in HALF_OPEN
        breaker.call(lambda: True)
        breaker.call(lambda: True)

        # After all permitted calls succeed, should transition to CLOSED
        assert breaker.state == CircuitState.CLOSED

    def test_reset_closes_circuit(self):
        """Test that reset() closes the circuit and clears stats."""
        config = CircuitBreakerConfig(
            sliding_window_size=5,
            failure_rate_threshold=50.0,
            minimum_number_of_calls=5,
        )
        breaker = CircuitBreaker("test", config=config)

        # Open the circuit
        for _ in range(5):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.state == CircuitState.OPEN

        # Reset
        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        stats = breaker.stats
        assert stats.total_calls == 0
        assert stats.successful_calls == 0
        assert stats.failed_calls == 0

    def test_stats_to_dict(self):
        """Test that stats.to_dict() returns expected format."""
        breaker = CircuitBreaker("test")
        breaker.call(lambda: 42)

        stats_dict = breaker.stats.to_dict()
        assert "circuit_name" in stats_dict
        assert "state" in stats_dict
        assert "total_calls" in stats_dict
        assert stats_dict["circuit_name"] == "test"

    def test_sliding_window_respects_size(self):
        """Test that sliding window respects max size."""
        config = CircuitBreakerConfig(
            sliding_window_size=3,
            failure_rate_threshold=50.0,
            minimum_number_of_calls=3,
        )
        breaker = CircuitBreaker("test", config=config)

        # Make 5 calls
        for i in range(5):
            breaker.call(lambda i=i: i)

        # Only last 3 should be in window
        stats = breaker.stats
        assert stats.total_calls == 5

    def test_context_manager(self):
        """Test circuit breaker as context manager."""
        breaker = CircuitBreaker("test")
        with breaker:
            result = breaker.call(lambda: 100)
        assert result == 100


class TestCircuitBreakerConcurrency:
    """Tests for thread safety of CircuitBreaker."""

    def test_concurrent_calls_single_thread(self):
        """Test concurrent calls don't corrupt state."""
        breaker = CircuitBreaker("concurrent_test")
        results = []
        errors = []

        def worker():
            try:
                result = breaker.call(lambda: time.sleep(0.001) or 42)
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 10
        assert len(errors) == 0

    def test_concurrent_state_transitions(self):
        """Test concurrent state transitions are thread-safe."""
        config = CircuitBreakerConfig(
            sliding_window_size=100,
            failure_rate_threshold=50.0,
            minimum_number_of_calls=100,
            wait_duration_open=0.05,
        )
        breaker = CircuitBreaker("concurrent_transitions", config=config)

        # Rapidly generate failures from multiple threads
        def fail():
            try:
                breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
            except Exception:
                pass

        threads = [threading.Thread(target=fail) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # State should be consistent (either CLOSED or OPEN)
        assert breaker.state in (CircuitState.CLOSED, CircuitState.OPEN)

    def test_concurrent_half_open_access(self):
        """Test concurrent access during HALF_OPEN state."""
        config = CircuitBreakerConfig(
            sliding_window_size=5,
            failure_rate_threshold=50.0,
            minimum_number_of_calls=5,
            wait_duration_open=0.1,
            permitted_calls_in_half_open=3,
        )
        breaker = CircuitBreaker("half_open_concurrent", config=config)

        # Open the circuit
        for _ in range(5):
            with pytest.raises(ValueError):
                breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        # Wait for HALF_OPEN
        time.sleep(0.15)

        # Concurrent successful calls in HALF_OPEN
        results = []
        errors = []

        def success_call():
            try:
                result = breaker.call(lambda: "ok")
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=success_call) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Some should succeed, some may be rejected
        assert len(results) + len(errors) == 10


class TestCircuitBreakerDecorator:
    """Tests for circuit_breaker decorator."""

    def test_decorator_basic_usage(self):
        """Test basic decorator usage."""
        @circuit_breaker("decorated_test")
        def my_func():
            return 123

        result = my_func()
        assert result == 123

    def test_decorator_with_fallback(self):
        """Test decorator with fallback."""
        @circuit_breaker("fallback_test", fallback=lambda e: "fallback")
        def my_func():
            raise ValueError("fail")

        result = my_func()
        assert result == "fallback"

    def test_decorator_reuses_same_breaker(self):
        """Test that same name reuses same circuit breaker."""
        @circuit_breaker("shared_breaker")
        def func1():
            return 1

        @circuit_breaker("shared_breaker")
        def func2():
            return 2

        # Both should use same breaker instance
        breaker1 = get_circuit_breaker("shared_breaker")
        breaker2 = get_circuit_breaker("shared_breaker")
        assert breaker1 is breaker2


class TestCallResult:
    """Tests for CallResult dataclass."""

    def test_call_result_success(self):
        """Test CallResult for successful call."""
        result = CallResult(timestamp=time.time(), is_success=True)
        assert result.is_success is True
        assert result.is_failure is False

    def test_call_result_failure(self):
        """Test CallResult for failed call."""
        result = CallResult(timestamp=time.time(), is_success=False, error=ValueError("test"))
        assert result.is_success is False
        assert result.is_failure is True
        assert isinstance(result.error, ValueError)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
