from __future__ import annotations

from app.observability.logging import configure_logging


def test_configure_logging_emits_json(capsys) -> None:
    configure_logging(service="test-api", level="INFO")
    import structlog

    structlog.get_logger().info("ready")
    out = capsys.readouterr().out
    assert "ready" in out
