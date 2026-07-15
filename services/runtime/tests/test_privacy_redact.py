from __future__ import annotations

from app.privacy.redact import redact_log_event, redact_messages, redact_text


def test_redact_phone_and_id() -> None:
    text = "联系我 13812345678 或身份证 110101199001011234"
    out = redact_text(text)
    assert "13812345678" not in out
    assert "[REDACTED_PHONE]" in out
    assert "110101199001011234" not in out
    assert "[REDACTED_ID]" in out


def test_redact_api_key_and_aws() -> None:
    text = "key=sk-abcdefghijklmnopqrstuvwxyz012345 and AKIAIOSFODNN7EXAMPLE"
    out = redact_text(text)
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in out
    assert "[REDACTED_API_KEY]" in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out


def test_redact_messages_preserves_structure() -> None:
    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "phone 13900001111 ok"}],
        }
    ]
    redacted = redact_messages(messages)
    assert messages[0]["content"][0]["text"].endswith("13900001111 ok")
    assert "[REDACTED_PHONE]" in redacted[0]["content"][0]["text"]


def test_redact_log_event() -> None:
    event = redact_log_event(None, "info", {"summary": "call 13700001111", "ok": True})
    assert "[REDACTED_PHONE]" in event["summary"]
    assert event["ok"] is True


def test_redact_leaves_normal_chinese_names() -> None:
    text = "张白鹿和李云龙在亮剑里。"
    assert redact_text(text) == text
