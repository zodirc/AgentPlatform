"""Query normalization + candidate ranking (§2.2.1).

Global rules only — no gold-patch / per-repo tuning (anti-overfit).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.structural.workspace_index.types import SymbolHit

# Path-segment tie-breaks (shallow depth still primary).
_PATH_PENALTY_SEGMENTS = frozenset(
    {"tests", "test", "testing", "examples", "example", "docs", "doc", "benchmarks"}
)
_PATH_BONUS_SEGMENTS = frozenset({"src", "lib", "astropy", "django", "sympy"})


@dataclass(frozen=True, slots=True)
class NormalizedQuery:
    """Tail + qualifier chain for symbol lookup."""

    raw: str
    tail: str  # last segment — primary postings key
    parts: tuple[str, ...]  # full dotted chain
    container_hint: str | None  # parent segment when len(parts) >= 2

    @property
    def is_qualified(self) -> bool:
        return len(self.parts) >= 2


def normalize_symbol_query(query: str) -> NormalizedQuery:
    """`astropy.io.fits.Card` → tail=Card; `Card.fromstring` → tail=fromstring, container=Card."""
    raw = (query or "").strip()
    parts = tuple(p for p in raw.split(".") if p)
    if not parts:
        return NormalizedQuery(raw=raw, tail=raw, parts=(), container_hint=None)
    tail = parts[-1]
    container = parts[-2] if len(parts) >= 2 else None
    return NormalizedQuery(
        raw=raw, tail=tail, parts=parts, container_hint=container
    )


def _match_tier(hit: SymbolHit, nq: NormalizedQuery) -> int:
    """Lower is better: 0 exact · 1 qualified-tail · 2 case-insensitive · 3 prefix · 9 other."""
    name = hit.name
    tail = nq.tail
    if not name or not tail:
        return 9
    if name == tail:
        if nq.is_qualified and hit.container:
            # Prefer container chain / hint alignment for qualified queries.
            ct = hit.container
            if nq.container_hint and (
                ct == nq.container_hint
                or ct.endswith("." + nq.container_hint)
                or nq.container_hint in ct.split(".")
            ):
                return 0
            if nq.parts and _container_matches_chain(ct, nq.parts[:-1]):
                return 0
            # Exact name without container confirm still strong.
            return 1
        return 0
    if name.lower() == tail.lower():
        return 2
    if name.startswith(tail) or name.lower().startswith(tail.lower()):
        return 3
    return 9


def _container_matches_chain(container: str, chain: tuple[str, ...]) -> bool:
    if not container or not chain:
        return False
    ct_parts = container.split(".")
    # Tail of container equals chain tail, or full suffix match.
    if ct_parts[-1] == chain[-1]:
        return True
    joined = ".".join(chain)
    return container == joined or container.endswith("." + joined)


def _kind_rank(kind: str) -> int:
    k = (kind or "").lower()
    if k in {"class", "interface", "struct", "enum", "type", "module"}:
        return 0
    if k in {"function", "def"}:  # top-level def
        return 1
    if k == "method":
        return 2
    if k in {"variable", "const", "assignment"}:
        return 3
    return 4


def _path_tiebreak(path: str) -> tuple[int, int, str]:
    """(penalty, depth, path) — lower better."""
    parts = path.replace("\\", "/").split("/")
    depth = len(parts)
    segs = {p.lower() for p in parts[:-1]}
    penalty = 0
    if segs & _PATH_PENALTY_SEGMENTS:
        penalty += 2
    if segs & _PATH_BONUS_SEGMENTS:
        penalty -= 1
    return (penalty, depth, path)


def rank_hits(hits: list[SymbolHit], nq: NormalizedQuery, *, limit: int) -> list[SymbolHit]:
    """§2.2.1 sort: match tier → kind → path depth / src-vs-tests → path,line."""
    scored: list[tuple[tuple, SymbolHit]] = []
    for h in hits:
        tier = _match_tier(h, nq)
        if tier >= 9 and h.name != nq.tail:
            # Keep case-insensitive / prefix already ranked; drop unrelated.
            if h.name.lower() != nq.tail.lower() and not h.name.lower().startswith(
                nq.tail.lower()
            ):
                continue
        key = (
            tier,
            _kind_rank(h.kind),
            _path_tiebreak(h.path),
            h.line,
        )
        scored.append((key, h))
    scored.sort(key=lambda x: x[0])
    return [h for _, h in scored[: max(1, int(limit))]]


def collect_candidate_hits(
    postings_exact: list[SymbolHit],
    *,
    nq: NormalizedQuery,
    all_names: dict[str, list[SymbolHit]] | None = None,
    limit: int = 20,
) -> list[SymbolHit]:
    """Gather exact + case-insensitive + prefix postings, then rank."""
    bucket: dict[tuple[str, int, str], SymbolHit] = {}

    def _add(items: list[SymbolHit]) -> None:
        for h in items:
            key = (h.path, h.line, h.name)
            bucket.setdefault(key, h)

    _add(postings_exact)
    if all_names and nq.tail:
        tail_l = nq.tail.lower()
        for name, items in all_names.items():
            if name == nq.tail:
                continue
            if name.lower() == tail_l or name.lower().startswith(tail_l):
                _add(items)
    return rank_hits(list(bucket.values()), nq, limit=limit)
