"""L2 语料装载：公版范本做人基线；产品章稿只抽特征不在本模块存正文。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from app.writing.signals.bank import Exemplar, load_platform_exemplars
from app.writing.signals.holdout import load_eval_holdout_exemplars


def literary_human_samples(*, include_holdout: bool = True) -> list[Exemplar]:
    """公版白话节选。这是文学人类基线，不是本仓模型产出。"""
    bank = load_platform_exemplars(work_mode="literary")
    rows: list[Exemplar] = []
    for samples in bank.values():
        rows.extend(samples)
    if include_holdout:
        hold = load_eval_holdout_exemplars()
        for samples in hold.values():
            rows.extend(samples)
    seen: set[str] = set()
    unique: list[Exemplar] = []
    for sample in rows:
        key = sample.text_sha256
        if key in seen:
            continue
        seen.add(key)
        unique.append(sample)
    return unique


def load_product_chapters(root: Path | None) -> list[dict[str, Any]]:
    """读已落盘章稿路径列表。调用方负责抽特征后丢正文。"""
    if root is None or not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for rel in ("drafts/manuscript.md", "manuscript.md"):
        path = root / rel
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if text.strip():
                out.append({"path": str(path), "text": text, "source": "product"})
    return out


def iter_sample_texts(samples: Iterable[Exemplar]) -> list[dict[str, Any]]:
    return [
        {
            "path": sample.slug,
            "text": sample.text,
            "source": "literary_exemplar",
            "work": sample.work,
            "fragment": sample.fragment,
        }
        for sample in samples
    ]
