"""
Unit tests for retry_policy module.
Tests all states, edge cases, and concurrent access.
"""

import time
import threading
import pytest
from typing import Set

# Private functions (_calculate_wait_duration, _is_retryable) are tested directly
# because they implement complex backoff/jitter algorithms that are difficult to
# verify thoroughly through the public @retry decorator API alone.
from scripts.retry_policy import (
    RetryConfig,
    RetryContext,
    RetryExhausted,
    retry,
    create_retry_policy,
    default_retry_policy,
    _calculate_wait_duration,
    _is_retryable,
)


class TestRetryConfig:
    """Tests for RetryConfig validation."""

    def test_default_config(self):
        """Test default configuration values."""
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.wait_duration_ms == 500
        assert config.exponential_backoff_multiplier == 2.0
        assert config.jitter is True
        assert config.jitter_max_ms == 100
        assert config.retryable_exceptions == set()

    def test_custom_config(self):
        """Test custom configuration."""
        config = RetryConfig(
            max_attempts=5,
            wait_duration_ms=1000,
            exponential_backoff_multiplier=1.5,
            jitter=False,
            jitter_max_ms=50,
        )
        assert config.max_attempts == 5
        assert config.wait_duration_ms == 1000
        assert config.exponential_backoff_multiplier == 1.5
        assert config.jitter is False

    def test_invalid_max_attempts(self):
        """Test that max_attempts < 1 raises ValueError."""
        with pytest.raises(ValueError, match="max_attempts must be at least 1"):
            RetryConfig(max_attempts=0)

    def test_invalid_wait_duration_ms(self):
        """Test that wait_duration_ms < 0 raises ValueError."""
        with pytest.raises(ValueError, match="wait_duration_ms must be non-negative"):
            RetryConfig(wait_duration_ms=-1)

    def test_invalid_exponential_backoff_multiplier(self):
        """Test that exponential_backoff_multiplier <= 0 raises ValueError."""
        with pytest.raises(ValueError, match="exponential_backoff_multiplier must be positive"):
            RetryConfig(exponential_backoff_multiplier=0)

    def test_invalid_jitter_max_ms(self):
        """Test that jitter_max_ms < 0 raises ValueError."""
        with pytest.raises(ValueError, match="jitter_max_ms must be non-negative"):
            RetryConfig(jitter_max_ms=-1)


class TestRetryContext:
    """Tests for RetryContext dataclass."""

    def test_retry_context_attributes(self):
        """Test RetryContext has correct attributes."""
        ctx = RetryContext(attempt=2, total_attempts=3, last_exception=ValueError("test"))
        assert ctx.attempt == 2
        assert ctx.total_attempts == 3
        assert isinstance(ctx.last_exception, ValueError)

    def test_retry_context_none_exception(self):
        """Test RetryContext with no exception."""
        ctx = RetryContext(attempt=1, total_attempts=3, last_exception=None)
        assert ctx.attempt == 1
        assert ctx.last_exception is None


class TestCalculateWaitDuration:
    """Tests for _calculate_wait_duration function."""

    def test_exponential_backoff_no_jitter(self):
        """Test exponential backoff without jitter."""
        config = RetryConfig(
            wait_duration_ms=100,
            exponential_backoff_multiplier=2.0,
            jitter=False,
        )
        lock = threading.Lock()

        # Attempt 1: 100ms
        wait1 = _calculate_wait_duration(config, 1, lock)
        assert wait1 == pytest.approx(0.1, rel=0.01)

        # Attempt 2: 100 * 2 = 200ms
        wait2 = _calculate_wait_duration(config, 2, lock)
        assert wait2 == pytest.approx(0.2, rel=0.01)

        # Attempt 3: 100 * 4 = 400ms
        wait3 = _calculate_wait_duration(config, 3, lock)
        assert wait3 == pytest.approx(0.4, rel=0.01)

    def test_exponential_backoff_with_jitter(self):
        """Test exponential backoff with jitter produces variable results."""
        config = RetryConfig(
            wait_duration_ms=100,
            exponential_backoff_multiplier=2.0,
            jitter=True,
            jitter_max_ms=50,
        )
        lock = threading.Lock()

        times = [_calculate_wait_duration(config, 1, lock) for _ in range(10)]

        # All times should be around 100ms +/- 50ms
        for t in times:
            assert 0.05 <= t <= 0.15

        # At least some should be different (jitter working)
        assert len(set(times)) > 1

    def test_custom_multiplier(self):
        """Test custom backoff multiplier."""
        config = RetryConfig(
            wait_duration_ms=100,
            exponential_backoff_multiplier=3.0,
            jitter=False,
        )
        lock = threading.Lock()

        # Attempt 1: 100
        # Attempt 2: 100 * 3 = 300
        # Attempt 3: 100 * 9 = 900
        wait3 = _calculate_wait_duration(config, 3, lock)
        assert wait3 == pytest.approx(0.9, rel=0.01)


class TestIsRetryable:
    """Tests for _is_retryable function."""

    def test_all_exceptions_retryable_when_empty(self):
        """Test that all exceptions are retryable when retryable_exceptions is empty."""
        config = RetryConfig()
        assert _is_retryable(config, ValueError("test")) is True
        assert _is_retryable(config, RuntimeError("test")) is True

    def test_specific_exceptions_retryable(self):
        """Test that only specified exceptions are retryable."""
        config = RetryConfig(retryable_exceptions={ConnectionError, TimeoutError})
        assert _is_retryable(config, ConnectionError("test")) is True
        assert _is_retryable(config, TimeoutError("test")) is True
        assert _is_retryable(config, ValueError("test")) is False

    def test_subclass_of_retryable_is_retryable(self):
        """Test that subclasses of retryable exceptions are retryable."""
        config = RetryConfig(retryable_exceptions={Exception})
        assert _is_retryable(config, ValueError("test")) is True


class TestRetryDecorator:
    """Tests for retry decorator."""

    def test_successful_first_attempt(self):
        """Test function succeeds on first attempt."""
        @retry
        def succeed():
            return 42

        result = succeed()
        assert result == 42

    def test_retry_on_failure_then_success(self):
        """Test retry when function fails then succeeds."""
        call_count = 0

        @retry(max_attempts=3, jitter=False, wait_duration_ms=10)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return 42

        result = flaky()
        assert result == 42
        assert call_count == 3

    def test_retry_exhausted(self):
        """Test RetryExhausted is raised when all attempts fail."""
        @retry(max_attempts=3, jitter=False, wait_duration_ms=10)
        def always_fails():
            raise ValueError("always failing")

        with pytest.raises(RetryExhausted) as exc_info:
            always_fails()

        assert exc_info.value.config.max_attempts == 3
        assert isinstance(exc_info.value.last_exception, ValueError)

    def test_non_retryable_exception_raises_immediately(self):
        """Test that non-retryable exceptions raise immediately."""
        call_count = 0

        @retry(max_attempts=3, retryable_exceptions={ConnectionError})
        def non_retryable():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError):
            non_retryable()

        assert call_count == 1

    def test_retryable_exception_retries(self):
        """Test that retryable exceptions trigger retries."""
        call_count = 0

        @retry(max_attempts=3, jitter=False, wait_duration_ms=10, retryable_exceptions={ValueError})
        def retryable():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("retryable")
            return "success"

        result = retryable()
        assert result == "success"
        assert call_count == 3

    def test_decorator_with_parentheses(self):
        """Test decorator with parentheses but no arguments."""
        @retry()
        def my_func():
            return 100

        assert my_func() == 100

    def test_decorator_syntax_variations(self):
        """Test different decorator syntax variations."""
        @retry(max_attempts=5)
        def func1():
            return 1

        result = retry(max_attempts=5)(lambda: 2)()
        assert func1() == 1
        assert result == 2

    def test_exception_preserved_in_retry_exhausted(self):
        """Test that the original exception is preserved in RetryExhausted."""
        original_error = ValueError("original message")

        @retry(max_attempts=2, jitter=False, wait_duration_ms=10)
        def fails():
            raise original_error

        with pytest.raises(RetryExhausted) as exc_info:
            fails()

        assert exc_info.value.last_exception is original_error


class TestCreateRetryPolicy:
    """Tests for create_retry_policy function."""

    def test_create_retry_policy(self):
        """Test creating a pre-configured retry policy."""
        policy = create_retry_policy(
            max_attempts=5,
            wait_duration_ms=200,
            exponential_backoff_multiplier=1.5,
        )

        @policy
        def my_func():
            return "done"

        assert my_func() == "done"

    def test_default_retry_policy(self):
        """Test default_retry_policy is configured correctly."""
        @default_retry_policy
        def my_func():
            return "done"

        assert my_func() == "done"


class TestRetryConcurrency:
    """Tests for thread safety of retry decorator."""

    def test_concurrent_retry_calls(self):
        """Test concurrent calls with retries don't interfere."""
        call_counts = []
        lock = threading.Lock()

        def make_flaky():
            count = 0
            def flaky():
                nonlocal count
                with lock:
                    count += 1
                if count < 3:
                    raise ValueError("fail")
                return count
            return flaky

        results = []
        errors = []

        def worker():
            try:
                policy = create_retry_policy(max_attempts=5, jitter=False, wait_duration_ms=5)
                func = policy(make_flaky())
                result = func()
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 5
        assert len(errors) == 0

    def test_jitter_thread_safety(self):
        """Test that jitter calculation is thread-safe."""
        config = RetryConfig(
            wait_duration_ms=100,
            exponential_backoff_multiplier=2.0,
            jitter=True,
            jitter_max_ms=50,
        )
        lock = threading.Lock()

        times = []
        results = []

        def calc_wait():
            t = _calculate_wait_duration(config, 1, lock)
            times.append(t)

        threads = [threading.Thread(target=calc_wait) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All times should be within expected range
        assert all(0.05 <= t <= 0.15 for t in times)


class TestRetryEdgeCases:
    """Edge case tests for retry decorator."""

    def test_zero_wait_duration(self):
        """Test retry with zero wait duration."""
        call_count = 0

        @retry(max_attempts=3, wait_duration_ms=0, jitter=False)
        def quick_fail():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "success"

        start = time.time()
        result = quick_fail()
        elapsed = time.time() - start

        assert result == "success"
        assert elapsed < 0.1  # Should be very fast with no wait

    def test_single_attempt(self):
        """Test retry with max_attempts=1."""
        @retry(max_attempts=1, jitter=False)
        def fail_once():
            raise ValueError("fail")

        with pytest.raises(RetryExhausted):
            fail_once()

    def test_multiple_exception_types(self):
        """Test retrying multiple different exception types."""
        call_count = 0

        @retry(max_attempts=5, jitter=False, wait_duration_ms=10)
        def multi_fail():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("conn")
            elif call_count == 2:
                raise TimeoutError("timeout")
            elif call_count == 3:
                raise ValueError("value")
            return "success"

        result = multi_fail()
        assert result == "success"
        assert call_count == 4

    def test_retry_with_args_and_kwargs(self):
        """Test retry with function that takes args and kwargs."""
        call_count = 0

        @retry(max_attempts=3, jitter=False, wait_duration_ms=10)
        def func_with_args(a, b, c=None):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("fail")
            return f"{a}-{b}-{c}"

        result = func_with_args("x", "y", c="z")
        assert result == "x-y-z"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
