from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_HASH_RE = re.compile(r"^[a-fA-F0-9]{32}$|^[a-fA-F0-9]{40}$|^[a-fA-F0-9]{64}$")
_IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)$"
)


def _ioc_dirs() -> list[Path]:
    """Fixture + standing seed IOC roots (docs seed/intel; offline only)."""
    app_root = Path(__file__).resolve().parents[2]  # .../app
    workspace = Path(os.environ.get("WORKSPACE_ROOT") or "/workspace")
    return [
        app_root / "scenarios" / "intel" / "fixtures" / "ioc",
        Path("/app/fixtures/intel/ioc"),
        # Standing seed (RO mount): demo cards + vendor fetch output
        workspace / "sources" / "seed" / "intel" / "ioc",
        workspace / "sources" / "seed" / "intel" / "vendor" / "ioc",
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


def _intel_corpus_roots() -> list[Path]:
    """Standing intel seed trees for exact lookup (offline; no vector)."""
    workspace = Path(os.environ.get("WORKSPACE_ROOT") or "/workspace")
    return [
        workspace / "sources" / "seed" / "intel",
        Path(__file__).resolve().parents[2] / "scenarios" / "intel" / "fixtures",
    ]


def _workspace_rel(path: Path) -> str:
    workspace = Path(os.environ.get("WORKSPACE_ROOT") or "/workspace")
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


async def lookup_indicator(
    indicator: str,
    limit: int = 8,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Exact/local indicator lookup — no embeddings, no network, no index sync.

    Complements ``enrich_ioc`` (structured IOC cards) with filename + small-file
    text hits under ``sources/seed/intel/**`` for ATT&CK ids, actor names, etc.
    """
    ind = (indicator or "").strip()
    if not ind:
        return {
            "status": "failed",
            "error": "indicator is required",
            "summary": "lookup_indicator: empty indicator",
            "hits": [],
        }

    limit = max(1, min(int(limit or 8), 20))
    needle = ind.lower()
    card = _load_card(ind)
    hits: list[dict[str, Any]] = []
    if card is not None:
        hits.append(
            {
                "kind": "ioc_card",
                "path": str(card.get("raw_ref") or ""),
                "indicator": card.get("normalized", ind),
                "excerpt": str(card.get("summary") or "")[:400],
                "score": 1.0,
                "tags": list(card.get("tags") or []),
            }
        )

    scanned = 0
    max_scan = 2500
    max_file_bytes = 64_000
    for root in _intel_corpus_roots():
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if scanned >= max_scan or len(hits) >= limit:
                break
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".md", ".json", ".txt", ".markdown"}:
                continue
            scanned += 1
            name_l = path.name.lower()
            rel = _workspace_rel(path)
            # Filename / path hit (ATT&CK ids, actor slugs)
            if needle in name_l or needle in rel.lower():
                excerpt = ""
                try:
                    if path.stat().st_size <= max_file_bytes:
                        excerpt = path.read_text(encoding="utf-8", errors="replace")[:400]
                except OSError:
                    excerpt = ""
                hits.append(
                    {
                        "kind": "path_match",
                        "path": rel,
                        "indicator": ind,
                        "excerpt": excerpt,
                        "score": 0.95,
                    }
                )
                if len(hits) >= limit:
                    break
                continue
            # Small-file content contains exact needle (case-insensitive)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size <= 0 or size > max_file_bytes:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if needle not in text.lower():
                continue
            # Prefer a window around first match
            low = text.lower()
            at = low.find(needle)
            start = max(0, at - 80)
            excerpt = text[start : start + 400]
            hits.append(
                {
                    "kind": "content_match",
                    "path": rel,
                    "indicator": ind,
                    "excerpt": excerpt,
                    "score": 0.85,
                }
            )
            if len(hits) >= limit:
                break

    # Dedupe by path
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for h in hits:
        key = f"{h.get('kind')}:{h.get('path')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(h)

    status = "ok" if deduped else "unknown"
    return {
        "status": status,
        "indicator": ind,
        "type": _guess_type(ind, "auto"),
        "hits": deduped[:limit],
        "scanned_files": scanned,
        "summary": (
            f"lookup_indicator: {len(deduped[:limit])} hit(s) for {ind}"
            if deduped
            else f"lookup_indicator: no local hit for {ind}"
        ),
        "hint": (
            None
            if deduped
            else "No exact local hit; try search_sources for semantic evidence — do not invent attribution."
        ),
        "retrieval": "exact-local",
    }
