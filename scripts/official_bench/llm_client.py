"""Minimal chat client for official bench (OpenAI-compatible or Anthropic Messages)."""

from __future__ import annotations

import json
import os
from typing import Any, Literal
from urllib.parse import urljoin

import httpx

ApiStyle = Literal["openai", "anthropic"]

_DEFAULT_TIMEOUT = float(os.environ.get("BENCH_MODEL_TIMEOUT_SECONDS", "240") or "240")


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
        )
    return _openai_complete(
        prompt,
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def _openai_complete(
    prompt: str,
    *,
    model: str,
    api_key: str,
    base_url: str,
    max_tokens: int,
    temperature: float,
) -> str:
    root = (base_url or "https://api.openai.com/v1").rstrip("/")
    if root.endswith("/chat/completions"):
        url = root
    else:
        url = f"{root}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    # OpenRouter recommends these; harmless elsewhere.
    if "openrouter.ai" in root:
        headers["HTTP-Referer"] = "https://localhost/ops"
        headers["X-Title"] = "AgentPlatform Ops Bench"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
        resp = client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            raise RuntimeError(f"openai-compat HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
    try:
        return str(data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"openai-compat unexpected response: {data!r}"[:500]) from exc


def _anthropic_complete(
    prompt: str,
    *,
    model: str,
    api_key: str,
    base_url: str,
    max_tokens: int,
    temperature: float,
) -> str:
    root = (base_url or "https://api.anthropic.com").rstrip("/")
    if root.endswith("/v1/messages"):
        url = root
    elif root.endswith("/v1"):
        url = f"{root}/messages"
    else:
        url = urljoin(root + "/", "v1/messages")
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
    with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
        resp = client.post(url, headers=headers, json=body)
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
