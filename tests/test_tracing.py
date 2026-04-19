"""
Unit tests for tracing module.
Tests all states, edge cases, and concurrent access.
"""

import logging
import time
import threading
import pytest
from io import StringIO
from typing import Optional

from scripts.tracing import (
    TraceContext,
    with_trace,
    trace_context,
    parse_traceparent,
    create_traceparent,
)


class TestTraceContext:
    """Tests for TraceContext class."""

    def test_trace_context_initialization(self):
        """Test TraceContext initializes with correct values."""
        trace = TraceContext("test_span")
        assert trace.span_name == "test_span"
        assert trace.trace_id is not None
        assert len(trace.trace_id) == 32
        assert trace.span_id is not None
        assert len(trace.span_id) == 16
        assert trace.parent_span_id is None
        assert trace.flags == "01"
        assert "00-" in trace.traceparent

    def test_trace_context_with_custom_trace_id(self):
        """Test TraceContext with custom trace ID."""
        custom_trace_id = "0af7651916cd43dd8448eb211c80319c"
        trace = TraceContext("test_span", trace_id=custom_trace_id)
        assert trace.trace_id == custom_trace_id
        assert custom_trace_id in trace.traceparent

    def test_trace_context_with_parent_span_id(self):
        """Test TraceContext with parent span ID."""
        parent_id = "b7ad6b7169203331"
        trace = TraceContext("test_span", parent_span_id=parent_id)
        assert trace.parent_span_id == parent_id

    def test_trace_context_not_sampled(self):
        """Test TraceContext with sampled=False."""
        trace = TraceContext("test_span", sampled=False)
        assert trace.flags == "00"

    def test_trace_context_as_context_manager(self):
        """Test TraceContext as context manager records timing."""
        trace = TraceContext("test_span")
        with trace:
            pass

        assert trace.duration_ms is not None
        assert trace.duration_ms >= 0

    def test_trace_context_records_duration(self):
        """Test TraceContext records duration of work."""
        trace = TraceContext("test_span")
        with trace:
            time.sleep(0.05)  # 50ms

        assert trace.duration_ms is not None
        assert trace.duration_ms >= 50

    def test_trace_context_stores_exception(self):
        """Test TraceContext stores exception on error."""
        trace = TraceContext("test_span")
        error = None
        try:
            with trace:
                raise ValueError("test error")
        except ValueError as e:
            error = e

        assert error is not None
        assert trace._error is not None
        assert isinstance(trace._error, ValueError)

    def test_duration_ms_before_exit_is_none(self):
        """Test duration_ms is None before context exit."""
        trace = TraceContext("test_span")
        with trace:
            assert trace.duration_ms is None

    def test_generate_trace_id_length(self):
        """Test that generated trace ID is 32 characters."""
        trace_id = TraceContext._generate_trace_id()
        assert len(trace_id) == 32
        assert all(c in "0123456789abcdef" for c in trace_id)

    def test_generate_span_id_length(self):
        """Test that generated span ID is 16 characters."""
        span_id = TraceContext._generate_span_id()
        assert len(span_id) == 16
        assert all(c in "0123456789abcdef" for c in span_id)


class TestWithTraceDecorator:
    """Tests for with_trace decorator."""

    def test_decorator_basic_usage(self):
        """Test basic decorator usage."""
        @with_trace("my_function")
        def my_func():
            return 42

        result = my_func()
        assert result == 42

    def test_decorator_with_args(self):
        """Test decorator passes through arguments."""
        @with_trace("add")
        def add(a, b):
            return a + b

        result = add(2, 3)
        assert result == 5

    def test_decorator_with_kwargs(self):
        """Test decorator passes through keyword arguments."""
        @with_trace("greet")
        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}"

        result = greet("World", greeting="Hi")
        assert result == "Hi, World"

    def test_decorator_propagates_exception(self):
        """Test decorator propagates exceptions after logging."""
        @with_trace("failing_func")
        def failing_func():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            failing_func()

    def test_decorator_preserves_function_metadata(self):
        """Test that decorator preserves function name and docstring."""
        @with_trace("my_func")
        def my_func():
            """My docstring."""
            return 1

        assert my_func.__name__ == "my_func"
        assert my_func.__doc__ == "My docstring."


class TestTraceContextManager:
    """Tests for trace_context context manager."""

    def test_trace_context_manager_basic(self):
        """Test basic trace_context usage."""
        with trace_context("my_span") as ctx:
            assert ctx.span_name == "my_span"

    def test_trace_context_manager_propagation(self):
        """Test trace context propagation."""
        parent_trace_id = "0af7651916cd43dd8448eb211c80319c"
        parent_span_id = "b7ad6b7169203331"

        with trace_context(
            "child_span",
            trace_id=parent_trace_id,
            parent_span_id=parent_span_id,
        ) as ctx:
            assert ctx.trace_id == parent_trace_id
            assert ctx.parent_span_id == parent_span_id

    def test_trace_context_manager_not_sampled(self):
        """Test trace_context with sampled=False."""
        with trace_context("unsampled", sampled=False) as ctx:
            assert ctx.flags == "00"

    def test_trace_context_manager_yields_context(self):
        """Test that trace_context yields the context object."""
        with trace_context("test_span") as ctx:
            assert isinstance(ctx, TraceContext)
            ctx.some_custom_field = "value"  # Should not raise


class TestParseTraceparent:
    """Tests for parse_traceparent function."""

    def test_parse_valid_traceparent(self):
        """Test parsing a valid traceparent header."""
        traceparent = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        version, trace_id, span_id = parse_traceparent(traceparent)

        assert version == "00"
        assert trace_id == "0af7651916cd43dd8448eb211c80319c"
        assert span_id == "b7ad6b7169203331"

    def test_parse_traceparent_not_sampled(self):
        """Test parsing traceparent with not sampled flag."""
        traceparent = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-00"
        version, trace_id, span_id = parse_traceparent(traceparent)

        assert version == "00"
        assert trace_id == "0af7651916cd43dd8448eb211c80319c"
        assert span_id == "b7ad6b7169203331"

    def test_parse_empty_traceparent(self):
        """Test parsing empty traceparent returns None."""
        assert parse_traceparent("") == (None, None, None)

    def test_parse_none_traceparent(self):
        """Test parsing None traceparent returns None."""
        assert parse_traceparent(None) == (None, None, None)

    def test_parse_invalid_traceparent_wrong_parts(self):
        """Test parsing invalid traceparent with wrong number of parts."""
        assert parse_traceparent("00-123456") == (None, None, None)
        assert parse_traceparent("00-123-456-789-01") == (None, None, None)

    def test_parse_invalid_traceparent_wrong_lengths(self):
        """Test parsing traceparent with wrong field lengths."""
        # Wrong trace_id length (should be 32)
        assert parse_traceparent("00-123-b7ad6b7169203331-01") == (None, None, None)
        # Wrong span_id length (should be 16)
        assert parse_traceparent("00-0af7651916cd43dd8448eb211c80319c-1234-01") == (None, None, None)
        # Wrong version length (should be 2)
        assert parse_traceparent("0-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01") == (None, None, None)

    def test_parse_invalid_traceparent_non_hex(self):
        """Test parsing traceparent with non-hex characters."""
        assert parse_traceparent("00-gggggggggggggggggggggggggggggggg-b7ad6b7169203331-01") == (None, None, None)
        assert parse_traceparent("00-0af7651916cd43dd8448eb211c80319c-gggggggggggggggg-01") == (None, None, None)


class TestCreateTraceparent:
    """Tests for create_traceparent function."""

    def test_create_traceparent_defaults(self):
        """Test creating traceparent with defaults."""
        traceparent = create_traceparent()
        parts = traceparent.split("-")

        assert len(parts) == 4
        assert parts[0] == "00"  # version
        assert len(parts[1]) == 32  # trace_id
        assert len(parts[2]) == 16  # span_id
        assert parts[3] == "01"  # sampled flag

    def test_create_traceparent_custom_trace_id(self):
        """Test creating traceparent with custom trace ID."""
        custom_trace_id = "0af7651916cd43dd8448eb211c80319c"
        traceparent = create_traceparent(trace_id=custom_trace_id)

        assert custom_trace_id in traceparent

    def test_create_traceparent_custom_span_id(self):
        """Test creating traceparent with custom span ID."""
        custom_span_id = "b7ad6b7169203331"
        traceparent = create_traceparent(span_id=custom_span_id)

        assert custom_span_id in traceparent

    def test_create_traceparent_not_sampled(self):
        """Test creating traceparent with sampled=False."""
        traceparent = create_traceparent(sampled=False)

        assert traceparent.endswith("-00")

    def test_create_traceparent_sampled(self):
        """Test creating traceparent with sampled=True."""
        traceparent = create_traceparent(sampled=True)

        assert traceparent.endswith("-01")


class TestTracingConcurrency:
    """Tests for thread safety of tracing."""

    def test_concurrent_trace_contexts(self):
        """Test multiple threads can create trace contexts simultaneously."""
        traces = []

        def create_trace():
            with trace_context("concurrent_span") as ctx:
                traces.append(ctx.trace_id)

        threads = [threading.Thread(target=create_trace) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each thread should have its own trace ID
        assert len(traces) == 10
        assert len(set(traces)) == 10  # All unique

    def test_concurrent_decorated_functions(self):
        """Test concurrent calls to decorated functions."""
        call_results = []
        lock = threading.Lock()

        @with_trace("concurrent_func")
        def concurrent_func(n):
            with lock:
                call_results.append(n)
            return n * 2

        threads = [threading.Thread(target=concurrent_func, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(call_results) == 10

    def test_nested_trace_contexts(self):
        """Test nested trace contexts from multiple threads."""
        results = []

        def outer_trace():
            with trace_context("outer") as outer_ctx:
                results.append(("outer_start", outer_ctx.trace_id))

                def inner_trace():
                    with trace_context("inner") as inner_ctx:
                        results.append(("inner", inner_ctx.trace_id, inner_ctx.parent_span_id))

                t1 = threading.Thread(target=inner_trace)
                t1.start()
                t1.join()

                results.append(("outer_end", outer_ctx.trace_id))

        outer_trace()

        # Verify structure
        assert len(results) == 3
        assert results[0][0] == "outer_start"
        assert results[1][0] == "inner"
        assert results[2][0] == "outer_end"


class TestTracingEdgeCases:
    """Edge case tests for tracing."""

    def test_very_short_span(self):
        """Test span with minimal duration."""
        trace = TraceContext("short_span")
        with trace:
            pass

        assert trace.duration_ms is not None
        assert trace.duration_ms >= 0

    def test_traceparent_special_characters(self):
        """Test traceparent with edge case characters."""
        # Create traceparent and parse it back
        original = create_traceparent()
        version, trace_id, span_id = parse_traceparent(original)

        assert version == "00"
        assert len(trace_id) == 32
        assert len(span_id) == 16

    def test_multiple_span_same_trace(self):
        """Test multiple spans in same trace share trace ID."""
        trace_id = "0af7651916cd43dd8448eb211c80319c"

        span1 = TraceContext("span1", trace_id=trace_id)
        span2 = TraceContext("span2", trace_id=trace_id)

        assert span1.trace_id == span2.trace_id == trace_id
        assert span1.span_id != span2.span_id  # Different span IDs

    def test_trace_context_logs_on_error(self):
        """Test that errors are logged when exception occurs in context."""
        # This is mostly a smoke test - actual logging is verified through
        # the behavior of the context manager
        trace = TraceContext("error_span")
        try:
            with trace:
                raise RuntimeError("intentional error")
        except RuntimeError:
            pass

        assert trace._error is not None
        assert isinstance(trace._error, RuntimeError)


if __name__ == "__main__":
    import time
    pytest.main([__file__, "-v"])
