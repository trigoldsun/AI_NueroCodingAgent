"""
Structured logging with JSON output support.

Provides a structured logger that outputs JSON-formatted logs with
consistent fields for observability and log aggregation systems.

Features:
    - JSON-formatted output for log aggregation
    - Configurable log levels
    - Context fields that persist across log calls
    - Standard log fields (timestamp, level, message, etc.)

Example:
    logger = StructuredLogger("my_service")
    logger.info("user_action", user_id=123, action="login")

    with logger.context(order_id="456"):
        logger.info("order_processed")  # Includes order_id automatically
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

__all__ = ["StructuredLogger", "JSONFormatter"]


class JSONFormatter(logging.Formatter):
    """
    Custom formatter that outputs log records as JSON strings.

    Suitable for log aggregation systems like ELK, Splunk, or Loki.

    Example output:
        {"timestamp": "2024-01-15T10:30:00.000Z", "level": "INFO", "message": "Hello", "service": "myapp", "user_id": 123}
    """

    def __init__(
        self,
        service_name: str = "app",
        include_extra: bool = True,
        timestamp_format: str = "iso",
    ) -> None:
        """
        Initialize the JSON formatter.

        Args:
            service_name: Name of the service for the 'service' field.
            include_extra: Whether to include extra fields from log record.
            timestamp_format: Format for timestamp - 'iso' or 'unix'.
        """
        super().__init__()
        self.service_name = service_name
        self.include_extra = include_extra
        self.timestamp_format = timestamp_format
        self._lock = threading.Lock()

    def format(self, record: logging.LogRecord) -> str:
        """
        Format the log record as a JSON string.

        Args:
            record: The logging LogRecord to format.

        Returns:
            JSON-formatted string representation of the log.
        """
        log_data: Dict[str, Any] = {
            "timestamp": self._format_timestamp(record.created),
            "level": record.levelname,
            "message": record.getMessage(),
            "service": self.service_name,
            "logger": record.name,
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        if self.include_extra:
            extra_fields = {k: v for k, v in record.__dict__.items() if k not in self._reserved_fields}
            # Merge extra fields at top level for cleaner output (ECGS structured logging)
            for k, v in extra_fields.items():
                log_data[k] = v

        return json.dumps(log_data, default=str)

    def _format_timestamp(self, timestamp: float) -> str:
        """Format timestamp according to configured format."""
        if self.timestamp_format == "iso":
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        return str(timestamp)

    @property
    def _reserved_fields(self) -> set:
        """Fields that should not be included in 'extra' to avoid duplication."""
        return {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "exc_info",
            "exc_text",
            "thread",
            "threadName",
            "message",
            "asctime",
        }


class StructuredLogger:
    """
    A structured logger that provides contextual logging with JSON output.

    Maintains a context dictionary that is automatically included in all
    log messages made within that context.

    Example:
        logger = StructuredLogger("payment_service")

        # Simple logging
        logger.info("payment_processed", amount=100.00, currency="USD")

        # With context
        with logger.context(order_id="12345", customer_id="C001"):
            logger.info("order_shipped")  # Includes order_id and customer_id
            with logger.context(tracking_id="TRACK999"):
                logger.info("tracking_updated")  # Includes all three IDs
    """

    def __init__(
        self,
        name: str,
        level: int = logging.INFO,
        json_output: bool = True,
        include_caller_info: bool = False,
    ) -> None:
        """
        Initialize a structured logger.

        Args:
            name: Name of the logger (typically __name__ of the module).
            level: Minimum log level to output.
            json_output: Whether to use JSON formatting (default True).
            include_caller_info: Whether to include file/line/function info.
        """
        self._name = name
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)
        self._context: Dict[str, Any] = {}
        self._context_lock = threading.RLock()
        self._include_caller_info = include_caller_info

        if json_output and not self._has_handlers():
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(JSONFormatter(service_name=name))
            self._logger.addHandler(handler)
            self._logger.propagate = False

    def _has_handlers(self) -> bool:
        """Check if logger already has handlers configured."""
        return bool(self._logger.handlers)

    @property
    def name(self) -> str:
        """Return the logger name."""
        return self._name

    _LOGRECORD_RESERVED: frozenset = frozenset({
        "name", "msg", "args", "created", "filename", "funcName",
        "levelname", "levelno", "lineno", "module", "msecs", "message",
        "pathname", "process", "processName", "relativeCreated", "stack_info",
        "exc_info", "exc_text", "thread", "threadName", "asctime",
    })

    def _build_extra(self, **kwargs: Any) -> Dict[str, Any]:
        """Build the extra dict with context and extra fields, filtered for LogRecord safety."""
        with self._context_lock:
            extra = dict(self._context)
        # Filter reserved LogRecord fields to avoid KeyError when passed to logging
        extra.update({k: v for k, v in kwargs.items() if k not in self._LOGRECORD_RESERVED})
        return extra

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log a debug message with optional structured fields."""
        extra = self._build_extra(**kwargs)
        self._logger.debug(message, extra=extra)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log an info message with optional structured fields."""
        extra = self._build_extra(**kwargs)
        self._logger.info(message, extra=extra)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log a warning message with optional structured fields."""
        extra = self._build_extra(**kwargs)
        self._logger.warning(message, extra=extra)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log an error message with optional structured fields."""
        extra = self._build_extra(**kwargs)
        self._logger.error(message, extra=extra)

    def critical(self, message: str, **kwargs: Any) -> None:
        """Log a critical message with optional structured fields."""
        extra = self._build_extra(**kwargs)
        self._logger.critical(message, extra=extra)

    def exception(self, message: str, **kwargs: Any) -> None:
        """Log an exception with traceback."""
        extra = self._build_extra(**kwargs)
        self._logger.exception(message, extra=extra)

    def context(self, **kwargs: Any) -> "_ContextManager":
        """
        Create a context manager that adds fields to all log messages within it.

        Args:
            **kwargs: Fields to add to the context.

        Returns:
            Context manager that adds fields on enter and removes on exit.

        Example:
            logger = StructuredLogger("myapp")
            with logger.context(user_id="123"):
                logger.info("user_logged_in")  # Includes user_id
        """
        return _ContextManager(self, kwargs)

    def child(self, name: str) -> "StructuredLogger":
        """
        Create a child logger with a qualified name.

        Args:
            name: Suffix to append to the parent logger name.

        Returns:
            New StructuredLogger with qualified name.
        """
        child_name = f"{self._name}.{name}"
        child = StructuredLogger(
            child_name,
            level=self._logger.level,
            json_output=False,
            include_caller_info=self._include_caller_info,
        )
        with self._context_lock:
            child._context = dict(self._context)
        return child

    def capture(self) -> "_CaptureContext":
        """
        Create a context manager that captures JSON output to an in-memory buffer.

        Returns:
            Context manager that yields a StringIO buffer containing captured JSON lines.

        Example:
            logger = StructuredLogger("myapp")
            with logger.capture() as buf:
                logger.info("event", user_id="U001")
            output = buf.getvalue()
            parsed = json.loads(output.strip())
        """
        return _CaptureContext(self)


class _ContextManager:
    """Internal context manager for StructuredLogger.context()."""

    def __init__(self, logger: StructuredLogger, fields: Dict[str, Any]) -> None:
        self._logger = logger
        self._fields = fields
        self._prev_context: Optional[Dict[str, Any]] = None

    def __enter__(self) -> Dict[str, Any]:
        with self._logger._context_lock:
            self._prev_context = dict(self._logger._context)
            self._logger._context.update(self._fields)
        return self._fields

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        with self._logger._context_lock:
            self._logger._context.clear()
            if self._prev_context:
                self._logger._context.update(self._prev_context)


class _CaptureContext:
    """Internal context manager for StructuredLogger.capture()."""

    def __init__(self, logger: StructuredLogger) -> None:
        self._logger = logger
        self._handlers: list = []
        self._old_streams: list = []

    def __enter__(self) -> StringIO:
        from io import StringIO

        self._buf = StringIO()
        for h in self._logger._logger.handlers:
            if hasattr(h, "stream"):
                self._handlers.append(h)
                self._old_streams.append(h.stream)
                h.stream = self._buf
        return self._buf

    def __exit__(self, *args: Any) -> None:
        for h, old_stream in zip(self._handlers, self._old_streams):
            h.stream = old_stream


def get_logger(name: str) -> StructuredLogger:
    """
    Get or create a structured logger by name.

    Args:
        name: Logger name (typically __name__ of the module).

    Returns:
        StructuredLogger instance.
    """
    return StructuredLogger(name)
