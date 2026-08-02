"""Minimal chat client for official bench (OpenAI-compatible or Anthropic Messages)."""

from __future__ import annotations

import json
import os
import random
import sys
import time
from typing import Any, Literal
from urllib.parse import urljoin

import httpx

ApiStyle = Literal["openai", "anthropic"]

_DEFAULT_TIMEOUT = float(os.environ.get("BENCH_MODEL_TIMEOUT_SECONDS", "240") or "240")
# Probe must fail fast in the Ops UI (not inherit the 240s eval timeout).
_PROBE_TIMEOUT = float(os.environ.get("BENCH_MODEL_PROBE_TIMEOUT_SECONDS", "20") or "20")
_DEFAULT_MAX_RETRIES = int(os.environ.get("BENCH_MODEL_MAX_RETRIES", "6") or "6")
_RETRY_BASE_SECONDS = float(os.environ.get("BENCH_MODEL_RETRY_BASE_SECONDS", "1.5") or "1.5")
_PROBE_MAX_RETRIES = int(os.environ.get("BENCH_MODEL_PROBE_MAX_RETRIES", "2") or "2")

_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def resolve_api_style(
    *,
    provider: str | None = None,
    api_style: str | None = None,
) -> ApiStyle:
    explicit = (api_style or os.environ.get("BENCH_MODEL_API_STYLE") or "").strip().lower()
    if explicit in {"openai", "anthropic"}:
        return explicit  # type: ignore[return-value]
    name = (provider or os.environ.get("BENCH_MODEL_PROVIDER") or "").strip().lower()
    if name in {"anthropic", "claude"}:
        return "anthropic"
    return "openai"


def _max_retries(override: int | None) -> int:
    n = _DEFAULT_MAX_RETRIES if override is None else override
    return max(1, int(n))


def _retry_base() -> float:
    return max(0.1, _RETRY_BASE_SECONDS)


def _is_retryable_exc(exc: BaseException) -> bool:
    return isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
            httpx.RemoteProtocolError,
            httpx.NetworkError,
        ),
    )


def _sleep_backoff(attempt: int, base: float) -> None:
    # attempt is 0-based; cap wait so long runs do not stall forever on one call
    delay = min(45.0, base * (2**attempt)) + random.uniform(0.0, 0.35)
    time.sleep(delay)


def _request_with_retries(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any],
    max_retries: int | None = None,
) -> httpx.Response:
    attempts = _max_retries(max_retries)
    base = _retry_base()
    last_exc: BaseException | None = None
    for i in range(attempts):
        try:
            with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
                resp = client.request(method, url, headers=headers, json=json_body)
            if resp.status_code >= 400 and resp.status_code in _RETRYABLE_STATUS:
                last_exc = RuntimeError(
                    f"HTTP {resp.status_code}: {resp.text[:300]}"
                )
                if i + 1 >= attempts:
                    raise last_exc
                print(
                    f"[bench-llm] retry {i + 1}/{attempts} status={resp.status_code}",
                    file=sys.stderr,
                    flush=True,
                )
                _sleep_backoff(i, base)
                continue
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not _is_retryable_exc(exc) or i + 1 >= attempts:
                raise
            print(
                f"[bench-llm] retry {i + 1}/{attempts} after {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            _sleep_backoff(i, base)
    assert last_exc is not None
    raise last_exc


def openai_chat_url(base_url: str = "") -> str:
    root = (base_url or "https://api.openai.com/v1").rstrip("/")
    if root.endswith("/chat/completions"):
        return root
    return f"{root}/chat/completions"


def anthropic_messages_url(base_url: str = "") -> str:
    root = (base_url or "https://api.anthropic.com").rstrip("/")
    if root.endswith("/v1/messages"):
        return root
    if root.endswith("/v1"):
        return f"{root}/messages"
    return urljoin(root + "/", "v1/messages")


def chat_complete(
    prompt: str,
    *,
    model: str,
    api_key: str,
    base_url: str = "",
    api_style: ApiStyle | str | None = None,
    provider: str | None = None,
    max_tokens: int = 256,
    temperature: float = 0.0,
    max_retries: int | None = None,
    extra_body: dict[str, Any] | None = None,
) -> str:
    style = resolve_api_style(provider=provider, api_style=api_style)
    if style == "anthropic":
        return _anthropic_complete(
            prompt,
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=max_tokens,
            temperature=temperature,
            max_retries=max_retries,
        )
    return _openai_complete(
        prompt,
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
        temperature=temperature,
        max_retries=max_retries,
        extra_body=extra_body,
        provider=provider,
    )


def probe_model(
    *,
    model: str,
    api_key: str,
    base_url: str = "",
    api_style: ApiStyle | str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """Short live round-trip from the same code path as context/coding benches."""
    style = resolve_api_style(provider=provider, api_style=api_style)
    resolved_url = (
        anthropic_messages_url(base_url)
        if style == "anthropic"
        else openai_chat_url(base_url)
    )
    t0 = time.perf_counter()
    try:
        # Connectivity probe: disable thinking so a tiny max_tokens still yields content.
        probe_extra: dict[str, Any] | None = None
        if "deepseek" in (model or "").lower() or "deepseek.com" in (base_url or "").lower():
            probe_extra = {"thinking": {"type": "disabled"}}
        text = chat_complete(
            "Reply with exactly: ok",
            model=model,
            api_key=api_key,
            base_url=base_url,
            api_style=style,
            provider=provider,
            max_tokens=32,
            temperature=0.0,
            max_retries=_PROBE_MAX_RETRIES,
            extra_body=probe_extra,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "ok": True,
            "latency_ms": latency_ms,
            "provider": (provider or "").strip() or None,
            "api_style": style,
            "model": model,
            "base_url": (base_url or "").strip() or None,
            "endpoint": resolved_url,
            "preview": (text or "")[:200],
        }
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "provider": (provider or "").strip() or None,
            "api_style": style,
            "model": model,
            "base_url": (base_url or "").strip() or None,
            "endpoint": resolved_url,
            "error": str(exc)[:500],
        }


def _openai_complete(
    prompt: str,
    *,
    model: str,
    api_key: str,
    base_url: str,
    max_tokens: int,
    temperature: float,
    max_retries: int | None = None,
    extra_body: dict[str, Any] | None = None,
    provider: str | None = None,
) -> str:
    url = openai_chat_url(base_url)
    root = (base_url or "https://api.openai.com/v1").rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    # OpenRouter recommends these; harmless elsewhere.
    if "openrouter.ai" in root:
        headers["HTTP-Referer"] = "https://localhost/ops"
        headers["X-Title"] = "AgentPlatform Ops Bench"
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if extra_body:
        body.update(extra_body)
    resp = _request_with_retries(
        "POST", url, headers=headers, json_body=body, max_retries=max_retries
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"openai-compat HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    try:
        choice0 = data["choices"][0]
        msg = choice0.get("message") or {}
        content = str(msg.get("content") or "").strip()
        reasoning = str(msg.get("reasoning_content") or "").strip()
        finish = choice0.get("finish_reason")
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"openai-compat unexpected response: {data!r}"[:500]) from exc

    # Thinking-on: final answer is `content` only. Do not retry with a larger
    # max_tokens on length truncation — that burns a full wasted CoT generation.
    # Callers must set a ceiling that covers CoT + answer on the first request.
    if not content:
        print(
            f"[bench-llm] empty content; reasoning_content_len={len(reasoning)} "
            f"finish_reason={finish} model={model} provider={provider or '-'} "
            f"max_tokens={max_tokens}"
            + (
                " (raise BENCH_*_MAX_TOKENS; no budget retry)"
                if finish == "length"
                else ""
            ),
            file=sys.stderr,
            flush=True,
        )
    return content


def _anthropic_complete(
    prompt: str,
    *,
    model: str,
    api_key: str,
    base_url: str,
    max_tokens: int,
    temperature: float,
    max_retries: int | None = None,
) -> str:
    url = anthropic_messages_url(base_url)
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = _request_with_retries(
        "POST", url, headers=headers, json_body=body, max_retries=max_retries
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"anthropic HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    parts: list[str] = []
    for block in data.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    text = "".join(parts).strip()
    if not text and isinstance(data, dict):
        raise RuntimeError(f"anthropic empty content: {json.dumps(data)[:500]}")
    return text
