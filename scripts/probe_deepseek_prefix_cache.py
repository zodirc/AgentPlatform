#!/usr/bin/env python3
"""Non-interactive DeepSeek prefix-cache probe (no Web / no Turn).

Compares two assemble layouts on the same model:

  A) runtime (step=N) in the *middle*  — old shape that breaks append-only history
  B) runtime after messages            — current ContextEngine layout

Each arm: warm request → append-only second request. Prints prompt_cache_hit_tokens.

Usage:
  export DEEPSEEK_API_KEY=sk-...   # or MODEL_API_KEY / BENCH_MODEL_API_KEY
  python scripts/probe_deepseek_prefix_cache.py
  python scripts/probe_deepseek_prefix_cache.py --model deepseek-v4-flash

Exit 0 if tail-arm step2 hit_ratio >= --min-hit-ratio (default 0.5).
Exit 2 if key missing; 1 if assertion fails.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

import httpx

STABLE_SYSTEM = (
    "You are a writing assistant for long-form manuscripts. "
    "Follow outline discipline, cite sources when asked, and prefer propose_patch. "
    + ("Style guide: clarity over flourish. " * 40)
)
STABLE_PROJECT = "[project_context]\n## outline.md\n" + ("- chapter note\n" * 80)
HISTORY_USER = "Please continue chapter 3 with one short paragraph about the river."
HISTORY_ASSISTANT = (
    "The river cut a silver line through the valley, and the wind carried wet earth. "
    * 20
)
APPEND_USER = "Good. Now tighten the last two sentences only. Reply with one sentence."


def _key() -> str:
    for name in ("DEEPSEEK_API_KEY", "MODEL_API_KEY", "BENCH_MODEL_API_KEY", "OPENAI_API_KEY"):
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    return ""


def _runtime(step: int, max_steps: int = 40) -> str:
    return (
        f"[runtime_context] scenario_id=writing step={step}/{max_steps} "
        f"steps_remaining={max(0, max_steps - step)}"
    )


def _messages_middle(*, step: int, with_append: bool) -> list[dict[str, str]]:
    """Old layout: system → project → runtime → history → (append)."""
    msgs = [
        {"role": "system", "content": STABLE_SYSTEM},
        {"role": "user", "content": STABLE_PROJECT},
        {"role": "user", "content": _runtime(step)},
        {"role": "user", "content": HISTORY_USER},
        {"role": "assistant", "content": HISTORY_ASSISTANT},
    ]
    if with_append:
        msgs.append({"role": "user", "content": APPEND_USER})
    return msgs


def _messages_tail(*, step: int, with_append: bool) -> list[dict[str, str]]:
    """New layout: system → project → history → (append) → runtime."""
    msgs = [
        {"role": "system", "content": STABLE_SYSTEM},
        {"role": "user", "content": STABLE_PROJECT},
        {"role": "user", "content": HISTORY_USER},
        {"role": "assistant", "content": HISTORY_ASSISTANT},
    ]
    if with_append:
        msgs.append({"role": "user", "content": APPEND_USER})
    msgs.append({"role": "user", "content": _runtime(step)})
    return msgs


def _complete(
    *,
    client: httpx.Client,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    resp = client.post(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "max_tokens": 32,
            "temperature": 0,
            "stream": False,
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage") or {}
    hit = int(usage.get("prompt_cache_hit_tokens") or 0)
    miss = int(usage.get("prompt_cache_miss_tokens") or 0)
    prompt = int(usage.get("prompt_tokens") or (hit + miss) or 0)
    return {
        "prompt_tokens": prompt,
        "hit": hit,
        "miss": miss if miss else max(0, prompt - hit),
        "hit_ratio": (hit / prompt) if prompt else 0.0,
        "completion": ((data.get("choices") or [{}])[0].get("message") or {}).get(
            "content", ""
        )[:80],
    }


def _run_arm(
    *,
    client: httpx.Client,
    base_url: str,
    api_key: str,
    model: str,
    name: str,
    builder,
    pause_s: float,
) -> dict[str, Any]:
    print(f"\n== arm={name} ==")
    warm = _complete(
        client=client,
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=builder(step=1, with_append=False),
    )
    print(
        f"  step1 warm  prompt={warm['prompt_tokens']} hit={warm['hit']} "
        f"miss={warm['miss']} ratio={warm['hit_ratio']:.2%}"
    )
    if pause_s > 0:
        time.sleep(pause_s)
    second = _complete(
        client=client,
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=builder(step=2, with_append=True),
    )
    print(
        f"  step2 append prompt={second['prompt_tokens']} hit={second['hit']} "
        f"miss={second['miss']} ratio={second['hit_ratio']:.2%}"
    )
    return {"warm": warm, "second": second}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.environ.get("MODEL_NAME", "deepseek-v4-flash"))
    parser.add_argument(
        "--base-url",
        default=os.environ.get("MODEL_BASE_URL", "https://api.deepseek.com"),
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=2.0,
        help="Seconds between warm and append (cache persist; default 2)",
    )
    parser.add_argument(
        "--min-hit-ratio",
        type=float,
        default=0.5,
        help="Require tail-arm step2 hit/prompt >= this (default 0.5)",
    )
    parser.add_argument(
        "--skip-middle",
        action="store_true",
        help="Only run tail arm (cheaper)",
    )
    args = parser.parse_args()

    api_key = _key()
    if not api_key:
        print(
            "ERROR: set DEEPSEEK_API_KEY (or MODEL_API_KEY / BENCH_MODEL_API_KEY)",
            file=sys.stderr,
        )
        return 2

    print(f"model={args.model} base={args.base_url} pause={args.pause}s")
    with httpx.Client() as client:
        results: dict[str, Any] = {}
        if not args.skip_middle:
            results["middle"] = _run_arm(
                client=client,
                base_url=args.base_url,
                api_key=api_key,
                model=args.model,
                name="runtime_middle (old)",
                builder=_messages_middle,
                pause_s=args.pause,
            )
            time.sleep(args.pause)
        results["tail"] = _run_arm(
            client=client,
            base_url=args.base_url,
            api_key=api_key,
            model=args.model,
            name="runtime_tail (new)",
            builder=_messages_tail,
            pause_s=args.pause,
        )

    tail_second = results["tail"]["second"]
    print("\n== verdict ==")
    print(
        f"tail step2 hit_ratio={tail_second['hit_ratio']:.2%} "
        f"(need >= {args.min_hit_ratio:.0%})"
    )
    if "middle" in results:
        mid = results["middle"]["second"]
        print(
            f"middle step2 hit_ratio={mid['hit_ratio']:.2%} "
            f"| delta_hit_tokens={tail_second['hit'] - mid['hit']}"
        )
        if mid["hit_ratio"] > 0 and mid["hit"] > 0:
            # Soft note only — DeepSeek may still hit system+project on middle.
            if tail_second["hit"] + 50 < mid["hit"]:
                print(
                    "NOTE: middle hit unexpectedly higher; check pause / account cache noise."
                )

    if tail_second["hit_ratio"] < args.min_hit_ratio:
        print(
            "FAIL: tail arm did not hit enough prefix cache. "
            "Retry with --pause 5; confirm model supports context caching.",
            file=sys.stderr,
        )
        return 1
    print("OK: tail arm prefix cache looks healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
