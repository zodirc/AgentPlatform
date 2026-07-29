from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_HASH_RE = re.compile(r"^[a-fA-F0-9]{32}$|^[a-fA-F0-9]{40}$|^[a-fA-F0-9]{64}$")
_IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)$"
)


def _ioc_dirs() -> list[Path]:
    """Fixture roots shipped with the runtime image / checkout (docs/39)."""
    app_root = Path(__file__).resolve().parents[2]  # .../app
    return [
        app_root / "scenarios" / "intel" / "fixtures" / "ioc",
        Path("/app/fixtures/intel/ioc"),
    ]


def _guess_type(indicator: str, explicit: str | None) -> str:
    t = (explicit or "auto").strip().lower()
    if t and t != "auto":
        return t
    ind = indicator.strip()
    if _IPV4_RE.match(ind):
        return "ip"
    if _HASH_RE.match(ind):
        return "hash"
    if "://" in ind:
        return "url"
    if "." in ind:
        return "domain"
    return "unknown"


def _load_card(indicator: str) -> dict[str, Any] | None:
    key = indicator.strip()
    # Also try basename without path noise
    candidates = {key, key.lower()}
    for root in _ioc_dirs():
        if not root.is_dir():
            continue
        for cand in list(candidates):
            path = root / f"{cand}.json"
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        # filename may use sanitized form
        for path in root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            ind = str(data.get("indicator") or data.get("normalized") or "").strip()
            if ind.lower() == key.lower():
                return data
    return None


async def enrich_ioc(
    indicator: str,
    type: str = "auto",  # noqa: A002 — tool schema field name
    **_kwargs: Any,
) -> dict[str, Any]:
    """Look up a local stub IOC card (docs/39). No outbound network."""
    ind = (indicator or "").strip()
    if not ind:
        return {
            "status": "failed",
            "error": "indicator is required",
            "summary": "enrich_ioc: empty indicator",
        }

    guessed = _guess_type(ind, type)
    card = _load_card(ind)
    if card is None:
        return {
            "status": "unknown",
            "indicator": ind,
            "type": guessed,
            "reputation_stub": "unknown",
            "tags": [],
            "related": [],
            "sources": [],
            "summary": f"enrich_ioc: no fixture for {ind}",
            "hint": "Search the local corpus or provide more context; do not invent attribution.",
        }

    out = {
        "status": "ok",
        "indicator": ind,
        "normalized": card.get("normalized", ind),
        "type": card.get("type", guessed),
        "reputation_stub": card.get("reputation_stub", "unknown"),
        "tags": list(card.get("tags") or []),
        "related": list(card.get("related") or []),
        "sources": list(card.get("sources") or []),
        "raw_ref": card.get("raw_ref"),
        "summary": card.get("summary")
        or f"enrich_ioc: {ind} → {card.get('reputation_stub', 'ok')}",
    }
    return out
