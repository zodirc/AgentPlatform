"""自然语言查询的有界 BM25。

只扫有限个源文件，按标识符切词后打分。没有向量依赖。
"""

from __future__ import annotations

import math
import os
import re
from pathlib import Path

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+|[\u4e00-\u9fff]{2,}")
_SOURCE_SUFFIXES = {".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java"}
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__"}


def bm25_file_hits(workspace: Path, query: str, *, limit: int = 8, max_files: int = 80) -> list[dict]:
    """对含空白的查询返回文件级命中。词太少时返回空列表。"""
    terms = _terms(query)
    if len(terms) < 2:
        return []
    docs = _read_docs(workspace, max_files=max_files)
    if not docs:
        return []
    df = {term: 0 for term in terms}
    prepared: list[tuple[str, list[str], str]] = []
    for rel, text in docs:
        tokens = _terms(text)
        prepared.append((rel, tokens, text))
        present = set(tokens)
        for term in terms:
            if term in present:
                df[term] += 1
    n_docs = len(prepared)
    scored: list[tuple[float, str, str]] = []
    avg = sum(len(tokens) for _, tokens, _ in prepared) / n_docs
    for rel, tokens, text in prepared:
        score = _bm25(tokens, terms, df, n_docs, avg or 1.0)
        if score <= 0:
            continue
        line = _first_line(text, terms)
        scored.append((score, rel, line))
    scored.sort(key=lambda item: item[0], reverse=True)
    hits = []
    for score, rel, line in scored[:limit]:
        hits.append(
            {
                "path": rel,
                "line": line,
                "score": round(score, 3),
                "bm25": True,
            }
        )
    return hits


def repo_map(workspace: Path, *, limit: int = 20) -> list[str]:
    """冷启动用地图：少量源文件的首个 def/func/type 行。"""
    lines: list[str] = []
    for rel, text in _read_docs(workspace, max_files=limit):
        signature = ""
        for raw in text.splitlines()[:80]:
            stripped = raw.strip()
            if stripped.startswith(("def ", "class ", "func ", "type ", "fn ")):
                signature = stripped[:120]
                break
        lines.append(f"{rel}: {signature}" if signature else rel)
        if len(lines) >= limit:
            break
    return lines


def _terms(text: str) -> list[str]:
    out: list[str] = []
    for match in _TOKEN_RE.finditer(text or ""):
        token = match.group(0)
        parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", token).replace("_", " ").split()
        for part in parts:
            lowered = part.lower()
            if len(lowered) >= 2:
                out.append(lowered)
    return out


def _bm25(
    tokens: list[str],
    terms: list[str],
    df: dict[str, int],
    n_docs: int,
    avg: float,
) -> float:
    if not tokens:
        return 0.0
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    score = 0.0
    k1 = 1.2
    b = 0.75
    for term in terms:
        freq = counts.get(term, 0)
        if freq <= 0:
            continue
        n_qi = df.get(term, 0)
        idf = math.log(1 + (n_docs - n_qi + 0.5) / (n_qi + 0.5))
        denom = freq + k1 * (1 - b + b * len(tokens) / avg)
        score += idf * (freq * (k1 + 1)) / denom
    return score


def _first_line(text: str, terms: list[str]) -> str:
    for raw in text.splitlines():
        lowered = raw.lower()
        if any(term in lowered for term in terms):
            return raw.strip()[:160]
    return ""


def _read_docs(workspace: Path, *, max_files: int) -> list[tuple[str, str]]:
    docs: list[tuple[str, str]] = []
    walked = 0
    for dirpath, dirnames, filenames in os.walk(workspace):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS and not name.startswith(".")]
        walked += 1
        if walked > 200:
            break
        for name in filenames:
            suffix = Path(name).suffix.lower()
            if suffix not in _SOURCE_SUFFIXES:
                continue
            path = Path(dirpath) / name
            try:
                if path.stat().st_size > 200_000:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel = path.relative_to(workspace).as_posix()
            docs.append((rel, text))
            if len(docs) >= max_files:
                return docs
    return docs
