"""Unit tests for official_bench.llm_client retries and probe helpers."""

from __future__ import annotations

import sys
from pathlib import Path
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from official_bench import llm_client  # noqa: E402


def test_openai_chat_url_appends_completions() -> None:
    assert llm_client.openai_chat_url("https://api.deepseek.com") == (
        "https://api.deepseek.com/chat/completions"
    )
    assert llm_client.openai_chat_url(
        "https://api.deepseek.com/chat/completions"
    ).endswith("/chat/completions")


def test_request_retries_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BENCH_MODEL_MAX_RETRIES", "3")
    monkeypatch.setenv("BENCH_MODEL_RETRY_BASE_SECONDS", "0.01")
    calls = {"n": 0}

    class BoomClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):  # noqa: ANN002
            return False

        def request(self, *args, **kwargs):  # noqa: ANN002, ANN003
            calls["n"] += 1
            if calls["n"] < 3:
                raise httpx.ConnectError("refused")
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ok"}}]},
                request=httpx.Request("POST", "https://example.test/v1/chat/completions"),
            )

    monkeypatch.setattr(llm_client.httpx, "Client", BoomClient)
    monkeypatch.setattr(llm_client, "_sleep_backoff", lambda *_a, **_k: None)

    text = llm_client.chat_complete(
        "hi",
        model="deepseek-v4-flash",
        api_key="sk-test",
        base_url="https://api.deepseek.com",
    )
    assert text == "ok"
    assert calls["n"] == 3


def test_request_retries_429_then_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BENCH_MODEL_MAX_RETRIES", "3")
    monkeypatch.setenv("BENCH_MODEL_RETRY_BASE_SECONDS", "0.01")
    calls = {"n": 0}

    class FlakyClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):  # noqa: ANN002
            return False

        def request(self, *args, **kwargs):  # noqa: ANN002, ANN003
            calls["n"] += 1
            req = httpx.Request("POST", "https://example.test/v1/chat/completions")
            if calls["n"] == 1:
                return httpx.Response(429, text="rate limit", request=req)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "done"}}]},
                request=req,
            )

    monkeypatch.setattr(llm_client.httpx, "Client", FlakyClient)
    monkeypatch.setattr(llm_client, "_sleep_backoff", lambda *_a, **_k: None)

    text = llm_client.chat_complete(
        "hi",
        model="m",
        api_key="k",
        base_url="https://api.openai.com/v1",
    )
    assert text == "done"
    assert calls["n"] == 2


def test_probe_model_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm_client,
        "chat_complete",
        lambda *a, **k: "ok",
    )
    out = llm_client.probe_model(
        model="deepseek-v4-flash",
        api_key="sk",
        base_url="https://api.deepseek.com",
        provider="deepseek",
    )
    assert out["ok"] is True
    assert out["model"] == "deepseek-v4-flash"
    assert out["endpoint"].endswith("/chat/completions")
    assert out["preview"] == "ok"


def test_openai_prefers_content_not_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    class Client:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):  # noqa: ANN002
            return False

        def request(self, *args, **kwargs):  # noqa: ANN002, ANN003
            req = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": "diff --git a/x b/x\n",
                                "reasoning_content": "I should write a patch...",
                            },
                        }
                    ]
                },
                request=req,
            )

    monkeypatch.setattr(llm_client.httpx, "Client", Client)
    text = llm_client.chat_complete(
        "hi",
        model="deepseek-v4-flash",
        api_key="k",
        base_url="https://api.deepseek.com",
        extra_body={"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
    )
    assert text.startswith("diff --git")
    assert "I should write" not in text


def test_openai_no_budget_retry_on_length_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Length+empty content must not re-call the API (wastes a full CoT)."""
    calls = {"n": 0}

    class Client:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):  # noqa: ANN002
            return False

        def request(self, *args, **kwargs):  # noqa: ANN002, ANN003
            calls["n"] += 1
            req = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "reasoning_content": "thinking" * 100,
                            },
                        }
                    ]
                },
                request=req,
            )

    monkeypatch.setattr(llm_client.httpx, "Client", Client)
    text = llm_client.chat_complete(
        "hi",
        model="deepseek-v4-flash",
        api_key="k",
        base_url="https://api.deepseek.com",
        max_tokens=4096,
    )
    assert text == ""
    assert calls["n"] == 1


def test_probe_model_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(llm_client, "chat_complete", boom)
    out = llm_client.probe_model(
        model="deepseek-v4-flash",
        api_key="sk",
        base_url="https://api.deepseek.com",
        provider="deepseek",
    )
    assert out["ok"] is False
    assert "refused" in (out.get("error") or "")
