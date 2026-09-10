"""组合账本：开篇集合与章承诺的结构化向量。罕见性用汉明距离，不存正文。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

LEDGER_REL = Path(".agent") / "work" / "ledger.jsonl"
ACCOUNT_LEDGER_REL = Path(".agent") / "account" / "ledger.jsonl"
VECTOR_KEYS: tuple[str, ...] = (
    "start_kind",
    "promise",
    "time_order",
    "subplot",
    "resolution_agency",
    "moral_polarity",
    "affect_mode",
    "locations",
    "place_class",
    "source_trust",
    "price_class",
    "entry_class",
)
NEAR_K = 20
HAMMING_MIN = 2
_SKIP_ENGINE = frozenset({"", "none", "other"})
_PRICE_AXES = frozenset({"lifespan", "memory", "contract", "status", "none"})
_PRICE_CANON = {
    "body_tax": "lifespan",
    "memory_tax": "memory",
    "paper_debt": "contract",
}
# Closed enums for Hamming, not content reject codes.
_BODY_PRICE = re.compile(
    r"烧寿|折寿|扣寿|偿命|阳寿|命税|换命|抵命|折阳|寿元|"
    r"以命换|用命修|寿命当|寿命结|三年寿"
)
_MEMORY_PRICE = re.compile(r"忘掉|忘记一个|永久失去|失去一段.{0,8}记忆|记忆被")
_PAPER_PRICE = re.compile(r"灵契|功簿|名册烙")
_MORTAL_ENTRY = re.compile(r"凡人|杂役|车夫|守夜|抄账|夹层|夹缝")


def ledger_path(*, workspace_root: Path, account: bool = False) -> Path:
    rel = ACCOUNT_LEDGER_REL if account else LEDGER_REL
    return Path(workspace_root).resolve() / rel


def encode_vector(raw: Mapping[str, Any] | None) -> dict[str, str]:
    src = raw or {}
    out: dict[str, str] = {}
    for key in VECTOR_KEYS:
        val = str(src.get(key) or "").strip().lower()
        if key == "price_class":
            val = _PRICE_CANON.get(val, val)
        out[key] = val
    return out


def hamming(a: Mapping[str, str], b: Mapping[str, str]) -> int:
    n = 0
    for key in VECTOR_KEYS:
        left, right = a.get(key) or "", b.get(key) or ""
        if not left or not right:
            continue
        if left != right:
            n += 1
    return n


def comparable_fields(a: Mapping[str, str], b: Mapping[str, str]) -> int:
    n = 0
    for key in VECTOR_KEYS:
        if (a.get(key) or "") and (b.get(key) or ""):
            n += 1
    return n


def append_ledger(
    vector: Mapping[str, Any],
    *,
    workspace_root: Path,
    kind: str,
) -> None:
    path = ledger_path(workspace_root=workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"kind": kind, "vector": encode_vector(vector)}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_ledger(*, workspace_root: Path, limit: int = NEAR_K) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in (
        ledger_path(workspace_root=workspace_root, account=True),
        ledger_path(workspace_root=workspace_root),
    ):
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            vec = data.get("vector") if isinstance(data, dict) else None
            if isinstance(vec, dict):
                rows.append(encode_vector(vec))
    return rows[-max(1, int(limit)) :]


def too_close_to_ledger(
    vectors: Sequence[Mapping[str, Any]],
    *,
    workspace_root: Path,
    k: int = NEAR_K,
    min_distance: int = HAMMING_MIN,
) -> tuple[str, str] | None:
    """组内同引擎、或相对近 K 条过近 → 拒。start_kind 正交不算换引擎。"""
    encoded = [encode_vector(v) for v in vectors]
    intra = _intra_engine_collision(encoded)
    if intra:
        return _reject(intra)
    history = load_ledger(workspace_root=workspace_root, limit=k)
    if not history:
        return None
    if any(_engine_near_history(vec, history) for vec in encoded):
        return _reject(_summarize(history[-8:]))
    closest: list[int] = []
    for vec in encoded:
        dists = []
        for old in history:
            if comparable_fields(vec, old) < 3:
                continue
            dists.append(hamming(vec, old))
        if dists:
            closest.append(min(dists))
    # 任一新卡贴着历史就算换皮；不能靠集合里一张远的把整组抬过线。
    if closest and min(closest) < min_distance:
        return _reject(_summarize(history[-8:]))
    return None


def _reject(used: str) -> tuple[str, str]:
    return (
        "ledger_too_close",
        "这组组合离账本里最近用过的太近。换叙事决策，不要换皮。"
        f" 已用过：{used}",
    )


def _intra_engine_collision(encoded: Sequence[Mapping[str, str]]) -> str:
    seen: dict[str, int] = {}
    for vec in encoded:
        pc = vec.get("price_class") or ""
        if pc in _SKIP_ENGINE:
            continue
        seen[pc] = seen.get(pc, 0) + 1
        if seen[pc] >= 2:
            return f"本组重复 {pc}"
    return ""


def _engine_near_history(
    vec: Mapping[str, str],
    history: Sequence[Mapping[str, str]],
) -> bool:
    pc = vec.get("price_class") or ""
    if pc in _SKIP_ENGINE:
        return False
    entry = vec.get("entry_class") or ""
    for old in history:
        if (old.get("price_class") or "") != pc:
            continue
        old_entry = old.get("entry_class") or ""
        if not entry or not old_entry or entry == old_entry:
            return True
    return False


def _summarize(rows: Iterable[Mapping[str, str]]) -> str:
    bits: list[str] = []
    for row in rows:
        part = "/".join(
            row[k]
            for k in ("start_kind", "price_class", "entry_class", "promise")
            if (row.get(k) or "") not in _SKIP_ENGINE
        )
        if part:
            bits.append(part)
    return "；".join(bits[:6]) or "（空）"


def _pond_blob(item: Mapping[str, Any]) -> str:
    return "".join(
        str(item.get(key) or "")
        for key in (
            "title",
            "flavor",
            "opening",
            "who",
            "where",
            "want",
            "price",
            "arc",
        )
    )


def classify_price(blob: str) -> str:
    if _BODY_PRICE.search(blob):
        return "lifespan"
    if _MEMORY_PRICE.search(blob):
        return "memory"
    if _PAPER_PRICE.search(blob):
        return "contract"
    return "none"


def classify_entry(blob: str) -> str:
    return "mortal" if _MORTAL_ENTRY.search(blob) else "other"


def pond_vector(item: Mapping[str, Any]) -> dict[str, str]:
    blob = _pond_blob(item)
    where = str(item.get("where") or "") + str(item.get("opening") or "")
    place = "transit" if any(tok in where for tok in ("地铁", "电梯", "高架")) else "other"
    declared = str(item.get("price_axis") or "").strip().lower()
    price = declared if declared in _PRICE_AXES else classify_price(blob)
    return encode_vector(
        {
            "start_kind": item.get("start_kind"),
            "promise": item.get("promise"),
            "place_class": place,
            "source_trust": item.get("source_trust"),
            "price_class": price,
            "entry_class": classify_entry(blob),
        }
    )
