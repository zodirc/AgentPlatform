from __future__ import annotations

from app.observability.logging import configure_logging


def test_configure_logging_json(capsys) -> None:
    configure_logging(service="test-runtime", level="INFO")
    import structlog

    structlog.get_logger().info("hello", turn_id="t1")
    captured = capsys.readouterr()
    assert "hello" in captured.out
    assert "test-runtime" in captured.out
