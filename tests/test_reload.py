import threading
import time

import pytest

from devpilot.watch.reload import ReloadDetector, ReloadResult


def test_detect_reload_from_lines():
    detector = ReloadDetector(
        patterns=["Started reloading", "Application startup complete"],
    )
    detector.feed_line("INFO:     Will watch for changes in these directories")
    detector.feed_line("INFO:     Started reloading")
    detector.feed_line("INFO:     Application startup complete")

    result = detector.get_result(timeout=1)
    assert result.status == "reloaded"


def test_detect_reload_failure():
    detector = ReloadDetector(
        patterns=["Application startup complete"],
    )
    detector.feed_line("  File \"app.py\", line 42")
    detector.feed_line("SyntaxError: unexpected indent")
    detector.mark_error("SyntaxError: unexpected indent")

    result = detector.get_result(timeout=1)
    assert result.status == "reload_failed"
    assert "SyntaxError" in result.error


def test_detect_timeout():
    detector = ReloadDetector(patterns=["never appears"])
    result = detector.get_result(timeout=0.1)
    assert result.status == "timeout"


def test_reload_time_tracked():
    detector = ReloadDetector(
        patterns=["Started reloading", "Application startup complete"],
    )
    detector.feed_line("Started reloading")
    time.sleep(0.05)
    detector.feed_line("Application startup complete")

    result = detector.get_result(timeout=1)
    assert result.status == "reloaded"
    assert result.reload_time_ms >= 40  # At least ~50ms minus tolerance


def test_error_patterns_detected():
    detector = ReloadDetector(patterns=["startup complete"])
    detector.feed_line("Traceback (most recent call last):")
    detector.feed_line('  File "app.py", line 10')
    detector.feed_line("ImportError: No module named 'foo'")
    detector.mark_error("ImportError: No module named 'foo'")

    result = detector.get_result(timeout=1)
    assert result.status == "reload_failed"
    assert "ImportError" in result.error
