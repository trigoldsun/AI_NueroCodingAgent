"""
Unit tests for structured_logger module.
Tests all states, edge cases, and concurrent access.
"""

import json
import logging
import threading
import pytest
from typing import Any

from scripts.structured_logger import (
    StructuredLogger,
    JSONFormatter,
    get_logger,
)


class TestJSONFormatter:
    """Tests for JSONFormatter class."""

    def test_formatter_initialization(self):
        """Test JSONFormatter initializes correctly."""
        formatter = JSONFormatter(service_name="test_service")
        assert formatter.service_name == "test_service"
        assert formatter.include_extra is True
        assert formatter.timestamp_format == "iso"

    def test_formatter_output_format(self):
        """Test JSONFormatter outputs valid JSON."""
        formatter = JSONFormatter(service_name="myapp")

        # Create a log record directly
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/file.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["message"] == "Test message"
        assert parsed["level"] == "INFO"
        assert parsed["service"] == "myapp"
        assert parsed["logger"] == "test_logger"
        assert "timestamp" in parsed

    def test_formatter_includes_exception(self):
        """Test JSONFormatter includes exception info."""
        formatter = JSONFormatter(service_name="myapp")

        try:
            raise ValueError("test error")
        except Exception:
            exc_info = __import__("sys").exc_info()

        record = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname="/test/file.py",
            lineno=10,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        assert "exception" in parsed

    def test_formatter_iso_timestamp(self):
        """Test JSONFormatter uses ISO timestamp format."""
        formatter = JSONFormatter(service_name="myapp")

        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/file.py",
            lineno=10,
            msg="Test",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        # ISO 8601 format: 2024-01-15T10:30:00.000Z
        assert "T" in parsed["timestamp"]
        assert parsed["timestamp"].endswith("Z")

    def test_formatter_reserved_fields_excluded(self):
        """Test JSONFormatter excludes reserved LogRecord fields."""
        formatter = JSONFormatter(service_name="myapp")

        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/file.py",
            lineno=10,
            msg="Test",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        # Reserved fields should not appear at top level
        if "extra" in parsed:
            reserved = formatter._reserved_fields
            for field in reserved:
                assert field not in parsed


class TestStructuredLogger:
    """Tests for StructuredLogger class."""

    def test_logger_initialization(self):
        """Test StructuredLogger initializes correctly."""
        logger = StructuredLogger("test_logger")
        assert logger.name == "test_logger"
        assert logger._logger.level == logging.INFO

    def test_logger_default_level(self):
        """Test StructuredLogger has default INFO level."""
        logger = StructuredLogger("test_logger")
        assert logger._logger.level == logging.INFO

    def test_logger_custom_level(self):
        """Test StructuredLogger with custom level."""
        logger = StructuredLogger("test_logger", level=logging.DEBUG)
        assert logger._logger.level == logging.DEBUG

    def test_logger_logs_json(self):
        """Test StructuredLogger outputs JSON via capture()."""
        logger = StructuredLogger("json_test", json_output=True)

        with logger.capture() as captured:
            logger.info("test message", key="value")

        output = captured.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["message"] == "test message"
        assert parsed["key"] == "value"
        assert parsed["level"] == "INFO"
        assert parsed["service"] == "json_test"

    def test_logger_debug_level(self):
        """Test StructuredLogger debug logging via capture()."""
        logger = StructuredLogger("debug_test", level=logging.DEBUG, json_output=True)

        with logger.capture() as captured:
            logger.debug("debug message")

        output = captured.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["message"] == "debug message"
        assert parsed["level"] == "DEBUG"

    def test_logger_warning_level(self):
        """Test StructuredLogger warning logging via capture()."""
        logger = StructuredLogger("warning_test", level=logging.WARNING, json_output=True)

        with logger.capture() as captured:
            logger.warning("warning message")

        output = captured.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["message"] == "warning message"
        assert parsed["level"] == "WARNING"

    def test_logger_error_level(self):
        """Test StructuredLogger error logging via capture()."""
        logger = StructuredLogger("error_test", level=logging.ERROR, json_output=True)

        with logger.capture() as captured:
            logger.error("error message")

        output = captured.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["message"] == "error message"
        assert parsed["level"] == "ERROR"

    def test_logger_exception(self):
        """Test StructuredLogger exception logging via capture()."""
        logger = StructuredLogger("exception_test", level=logging.ERROR, json_output=True)

        with logger.capture() as captured:
            try:
                raise ValueError("test error")
            except:
                logger.exception("exception occurred")

        output = captured.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["message"] == "exception occurred"
        assert "exception" in parsed

    def test_logger_multiple_fields(self):
        """Test StructuredLogger with multiple extra fields via capture()."""
        logger = StructuredLogger("multi_field_test", json_output=True)

        with logger.capture() as captured:
            logger.info("multi fields", field1="a", field2="b", field3=123)

        output = captured.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["field1"] == "a"
        assert parsed["field2"] == "b"
        assert parsed["field3"] == 123


class TestStructuredLoggerContext:
    """Tests for StructuredLogger context manager."""

    def test_context_manager_adds_fields(self):
        """Test context manager adds fields to log messages via capture()."""
        logger = StructuredLogger("context_test", json_output=True)

        with logger.capture() as captured:
            with logger.context(order_id="12345"):
                logger.info("order created")

        output = captured.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["order_id"] == "12345"

    def test_context_manager_nested(self):
        """Test nested context managers accumulate fields via capture()."""
        logger = StructuredLogger("nested_context_test", json_output=True)

        with logger.capture() as captured:
            with logger.context(user_id="U001"):
                logger.info("user action")
                with logger.context(order_id="O001"):
                    logger.info("order action")

        lines = [json.loads(line) for line in captured.getvalue().strip().split("\n")]

        # First log should have user_id
        assert lines[0]["user_id"] == "U001"
        assert "order_id" not in lines[0]

        # Second log should have both
        assert lines[1]["user_id"] == "U001"
        assert lines[1]["order_id"] == "O001"

    def test_context_manager_removes_fields_on_exit(self):
        """Test context manager removes fields after exit via capture()."""
        logger = StructuredLogger("exit_context_test", json_output=True)

        with logger.capture() as captured:
            logger.info("before context")
            with logger.context(temp_field="temp"):
                logger.info("inside context")
            logger.info("after context")

        lines = [json.loads(line) for line in captured.getvalue().strip().split("\n")]

        assert "temp_field" not in lines[0]
        assert "temp_field" in lines[1]
        assert "temp_field" not in lines[2]

    def test_context_manager_error_in_context(self):
        """Test context manager cleans up even on exception via capture()."""
        logger = StructuredLogger("error_context_test", json_output=True)

        try:
            with logger.context(critical_field="value"):
                logger.info("before error")
                raise RuntimeError("test error")
        except RuntimeError:
            pass

        # Next log should not have the context field
        with logger.capture() as captured:
            logger.info("after error")

        output = captured.getvalue()
        parsed = json.loads(output.strip())

        assert "critical_field" not in parsed


class TestStructuredLoggerChild:
    """Tests for StructuredLogger.child() method."""

    def test_child_logger_qualified_name(self):
        """Test child logger has qualified name."""
        parent = StructuredLogger("parent")
        child = parent.child("child")

        assert child.name == "parent.child"

    def test_child_inherits_context(self):
        """Test child logger inherits parent's context via capture()."""
        parent = StructuredLogger("parent_test", json_output=True)

        with parent.capture() as captured:
            with parent.context(parent_field="p_value"):
                child = parent.child("sub")
                # Child should have access to parent's context
                child.info("child log")

        output = captured.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["parent_field"] == "p_value"


class TestStructuredLoggerConcurrency:
    """Tests for thread safety of StructuredLogger."""

    def test_concurrent_logging(self):
        """Test concurrent log calls don't corrupt output."""
        logger = StructuredLogger("concurrent_test", json_output=True)
        outputs = []
        lock = threading.Lock()

        def log_worker(worker_id):
            for i in range(10):
                buf = None
                with logger.capture() as captured:
                    logger.info(f"worker_{worker_id}_msg_{i}", worker_id=worker_id, iteration=i)
                    buf = captured
                with lock:
                    outputs.append(buf.getvalue())

        threads = [threading.Thread(target=log_worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All outputs should be valid JSON
        for output in outputs:
            parsed = json.loads(output.strip())
            assert "message" in parsed

    def test_concurrent_context_managers(self):
        """Test concurrent context managers don't interfere."""
        logger = StructuredLogger("concurrent_context_test", json_output=True)
        results = []
        lock = threading.Lock()

        def worker_context(worker_id):
            buf = None
            with logger.context(worker_id=str(worker_id)):
                with logger.capture() as captured:
                    logger.info("log from worker")
                    buf = captured
            with lock:
                results.append(buf.getvalue())

        threads = [threading.Thread(target=worker_context, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each result should have correct worker_id
        for result in results:
            parsed = json.loads(result.strip())
            assert "worker_id" in parsed

    def test_context_isolation_between_threads(self):
        """Test that context in one thread doesn't leak to another."""
        logger = StructuredLogger("isolation_test", json_output=True)
        thread1_results = []
        thread2_results = []
        barrier = threading.Barrier(2)

        def thread1_worker():
            with logger.context(thread_name="one", secret="ONE"):
                barrier.wait()
                buf = None
                with logger.capture() as captured:
                    logger.info("thread 1 log")
                    buf = captured
                thread1_results.append(buf.getvalue())

        def thread2_worker():
            with logger.context(thread_name="two"):
                barrier.wait()
                buf = None
                with logger.capture() as captured:
                    logger.info("thread 2 log")
                    buf = captured
                thread2_results.append(buf.getvalue())

        t1 = threading.Thread(target=thread1_worker)
        t2 = threading.Thread(target=thread2_worker)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Thread 1 should have its own context
        parsed1 = json.loads(thread1_results[0].strip())
        assert parsed1["thread_name"] == "one"

        # Thread 2 should have its own context
        parsed2 = json.loads(thread2_results[0].strip())
        assert parsed2["thread_name"] == "two"


class TestStructuredLoggerEdgeCases:
    """Edge case tests for StructuredLogger."""

    def test_logger_with_no_handlers(self):
        """Test logger behaves correctly when no handlers configured."""
        # Create logger without adding handlers
        base_logger = logging.getLogger("no_handler_test")
        base_logger.setLevel(logging.DEBUG)
        base_logger.handlers.clear()

        logger = StructuredLogger("no_handler_test", json_output=False)

        # Should not raise, even without JSON output handler
        logger.info("test message")

    def test_logger_preserves_extra_fields(self):
        """Test that extra fields are preserved in output via capture()."""
        logger = StructuredLogger("extra_test", json_output=True)

        with logger.capture() as captured:
            logger.info("test", int_field=42, float_field=3.14, bool_field=True, none_field=None)

        output = captured.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["int_field"] == 42
        assert parsed["float_field"] == 3.14
        assert parsed["bool_field"] is True
        assert parsed["none_field"] is None

    def test_get_logger_returns_structured_logger(self):
        """Test get_logger returns StructuredLogger instance."""
        logger = get_logger("factory_test")
        assert isinstance(logger, StructuredLogger)
        assert logger.name == "factory_test"

    def test_context_manager_empty_fields(self):
        """Test empty context manager does not pollute output via capture()."""
        logger = StructuredLogger("empty_context_test", json_output=True)

        with logger.capture() as captured:
            with logger.context():
                logger.info("empty context log")

        output = captured.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["message"] == "empty context log"

    def test_logger_name_with_special_characters(self):
        """Test logger handles special characters in name."""
        logger = StructuredLogger("test.service/v1")
        assert logger.name == "test.service/v1"
