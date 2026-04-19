"""
Distributed tracing with W3C Trace Context support.

Implements the W3C Trace Context specification for distributed tracing.
traceparent header format: 00-{trace_id}-{span_id}-{flags}

Features:
    - @with_trace(span_name) decorator for tracing function execution
    - TraceContext context manager for manual tracing
    - Auto-records start time, end time, duration, and exceptions to logger
    - Generates compliant traceparent headers
    - Supports trace propagation across service boundaries

Example:
    @with_trace("fetch_user_data")
    def fetch_user(user_id: int) -> dict:
        ...

    with TraceContext("process_request") as trace:
        # your code here
        pass
"""

import logging
import secrets
import time
from contextlib import contextmanager
from functools import wraps
from typing import Optional, Callable, Any, Generator

logger = logging.getLogger(__name__)


class TraceContext:
    """
    Context manager for distributed tracing with W3C Trace Context.

    Automatically records start time, end time, duration, and exceptions
    to the logger when the context exits.

    Attributes:
        span_name: Name identifier for this span.
        trace_id: 32-character hex string identifying the trace.
        span_id: 16-character hex string identifying this span.
        flags: 2-character hex string with trace flags (01 = sampled).
        traceparent: Full W3C traceparent header value.

    Example:
        with TraceContext("my_operation") as trace:
            # Perform operation
            pass
        # Logger receives: start, end, duration, and any exception info
    """

    VERSION: str = "00"
    FLAGS_SAMPLED: str = "01"
    FLAGS_NOT_SAMPLED: str = "00"

    def __init__(
        self,
        span_name: str,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        sampled: bool = True,
    ) -> None:
        """
        Initialize a TraceContext.

        Args:
            span_name: Human-readable name for this span.
            trace_id: 32-character hex trace ID. Auto-generated if None.
            parent_span_id: 16-character hex ID of the parent span, if any.
            sampled: Whether this trace should be sampled (default True).
        """
        self.span_name = span_name
        self.trace_id = trace_id or self._generate_trace_id()
        self.span_id = self._generate_span_id()
        self.parent_span_id = parent_span_id
        self.flags = self.FLAGS_SAMPLED if sampled else self.FLAGS_NOT_SAMPLED
        self.traceparent = f"{self.VERSION}-{self.trace_id}-{self.span_id}-{self.flags}"

        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None
        self._duration_ms: Optional[float] = None
        self._error: Optional[Exception] = None

    @staticmethod
    def _generate_trace_id() -> str:
        """Generate a 32-character hex string for trace ID."""
        return ''.join(secrets.choice('0123456789abcdef') for _ in range(32))

    @staticmethod
    def _generate_span_id() -> str:
        """Generate a 16-character hex string for span ID."""
        return ''.join(secrets.choice('0123456789abcdef') for _ in range(16))

    def __enter__(self) -> "TraceContext":
        """Enter the tracing context and record start time."""
        self._start_time = time.perf_counter()
        logger.debug(
            "trace_start",
            extra={
                "span_name": self.span_name,
                "trace_id": self.trace_id,
                "span_id": self.span_id,
                "parent_span_id": self.parent_span_id,
                "traceparent": self.traceparent,
            },
        )
        return self

    def __exit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Any) -> bool:
        """Exit the tracing context and record end time, duration, and exception if any."""
        self._end_time = time.perf_counter()
        self._duration_ms = (self._end_time - self._start_time) * 1000
        self._error = exc_val

        if exc_val is not None:
            logger.warning(
                "trace_end",
                extra={
                    "span_name": self.span_name,
                    "trace_id": self.trace_id,
                    "span_id": self.span_id,
                    "traceparent": self.traceparent,
                    "duration_ms": round(self._duration_ms, 3),
                    "error": type(exc_val).__name__,
                    "error_message": str(exc_val),
                },
            )
        else:
            logger.debug(
                "trace_end",
                extra={
                    "span_name": self.span_name,
                    "trace_id": self.trace_id,
                    "span_id": self.span_id,
                    "traceparent": self.traceparent,
                    "duration_ms": round(self._duration_ms, 3),
                },
            )
        return False  # Do not suppress exceptions

    @property
    def duration_ms(self) -> Optional[float]:
        """Return the duration of this span in milliseconds, or None if not yet ended."""
        return self._duration_ms


def with_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator to trace a function's execution with W3C Trace Context.

    Wraps a function to automatically create a TraceContext, record
    execution time, and log any exceptions that occur.

    Args:
        span_name: Name for the span (typically the function name or operation).

    Returns:
        Decorated function that traces execution.

    Example:
        @with_trace("calculate_sum")
        def calculate_sum(a: int, b: int) -> int:
            return a + b

        result = calculate_sum(1, 2)  # Logs: start, end, duration
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with TraceContext(span_name) as trace:
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    # Re-raise after the context manager logs the exception
                    raise

        return wrapper
    return decorator


@contextmanager
def trace_context(
    span_name: str,
    trace_id: Optional[str] = None,
    parent_span_id: Optional[str] = None,
    sampled: bool = True,
) -> Generator[TraceContext, None, None]:
    """
    Context manager factory for creating a TraceContext with optional propagation.

    Provides explicit control over trace context creation, useful when
    extracting trace context from incoming headers (e.g., from an HTTP request).

    Args:
        span_name: Human-readable name for this span.
        trace_id: Optional 32-char hex trace ID to propagate an existing trace.
        parent_span_id: Optional 16-char hex ID of the parent span.
        sampled: Whether this trace should be sampled (default True).

    Yields:
        TraceContext instance with the traceparent header value.

    Example:
        # Propagate an existing trace from incoming headers
        incoming_traceparent = request.headers.get("traceparent")
        trace_id, parent_span_id = parse_traceparent(incoming_traceparent)

        with trace_context("handle_request", trace_id=trace_id, parent_span_id=parent_span_id) as ctx:
            # ctx.traceparent can be passed to outgoing requests
            outgoing_headers["traceparent"] = ctx.traceparent
            ...
    """
    context = TraceContext(
        span_name=span_name,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        sampled=sampled,
    )
    yield context


def parse_traceparent(traceparent: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse a W3C traceparent header value into its components.

    Args:
        traceparent: Full traceparent string (e.g., "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")

    Returns:
        Tuple of (version, trace_id, span_id). Returns (None, None, None) if invalid.

    Example:
        version, trace_id, span_id = parse_traceparent(
            "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        )
        # trace_id = "0af7651916cd43dd8448eb211c80319c"
        # span_id = "b7ad6b7169203331"
    """
    if not traceparent:
        return None, None, None

    parts = traceparent.split("-")
    if len(parts) != 4:
        return None, None, None

    version, trace_id, span_id, flags = parts

    # Validate lengths per W3C Trace Context spec
    if len(version) != 2 or len(trace_id) != 32 or len(span_id) != 16 or len(flags) != 2:
        return None, None, None

    # Validate hex characters
    hex_chars = set("0123456789abcdef")
    if not all(c in hex_chars for c in trace_id + span_id):
        return None, None, None

    return version, trace_id, span_id


def create_traceparent(
    trace_id: Optional[str] = None,
    span_id: Optional[str] = None,
    sampled: bool = True,
) -> str:
    """
    Create a W3C traceparent header value.

    Args:
        trace_id: Optional 32-char hex trace ID. Auto-generated if None.
        span_id: Optional 16-char hex span ID. Auto-generated if None.
        sampled: Whether trace is sampled (default True).

    Returns:
        Full traceparent header value.

    Example:
        header = create_traceparent()
        # header = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    """
    if trace_id is None:
        trace_id = TraceContext._generate_trace_id()
    if span_id is None:
        span_id = TraceContext._generate_span_id()

    flags = TraceContext.FLAGS_SAMPLED if sampled else TraceContext.FLAGS_NOT_SAMPLED
    return f"{TraceContext.VERSION}-{trace_id}-{span_id}-{flags}"
