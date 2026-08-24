"""源文档切块与嵌入文本组装（RAG 索引平面的「文档 → chunk」层）。

English: Index-time document→chunk layer — sectioning, wide-table dual-track,
embed-text assembly. Not on the search hot path.

=============================================================================
职责边界
=============================================================================
- **本模块**：可索引门控、Markdown/代码分节、宽 GFM 表剥离与行组线性化、
  chunk 元数据（行号 / citation / tags）、``build_embed_text`` 拼嵌入输入、
  ``chunk_source_text``（同步 embed 或 ``embed=False`` 延迟批量向量化）。
- **不在本模块**：ANN/BM25 检索（``pgvector_store`` / ``vector_index``）、
  超长窗 snap 细节（``chunk_split``）、模型加载（``embedder``）。
- **调用时机**：仅 Turn 外 sync / index；``search_sources`` **不**再切块。

链路位置::

  sources/ 扫描 → should_index_source → chunk_source_text
      → build_embed_text → embedder / index_embed → source_chunks

=============================================================================
Chunk 是什么（心智模型）
=============================================================================
一条 chunk = **业务记录**（dict / ``source_chunks`` 行），不是「向量本身」。

典型字段::

  chunk_id       path#chunk-N（同文件多段）
  path           源文件相对路径（一篇文档可对应 N 条 chunk）
  text           正文片段 → BM25 / excerpt / 引用展示
  section_title  所属标题
  line_start/end 原文行号（便于 read_file 定位）
  citation_id    cite:{stem}
  tags / symbol  稀疏标签与代码符号名
  vector         或 embed_input → 最终写入 embedding 列

两层「大小」不要混::

  文本长度（可变）   目标上限 ~450 token（settings）；小节可远小于此
  向量维度（固定）   Hash 256 / gte-small 384 / bge-m3 1024 ——
                     与 text 长短无关；短文仍输出同维稠密向量，
                     只是语义覆盖面更窄。

送入 embedder 的是 ``build_embed_text(...)`` 拼出的**字符串**
（标题面包屑 + 可选 path/tags + part），不是整份 chunk JSON。

文档总大小不切换算法：小文件 → 少 chunk；大文件 → 多 chunk；
每条仍受同一 token 预算约束（靠数量覆盖全文，不靠放大单 chunk）。

=============================================================================
切完之后如何进向量模型（与 embedder / index_embed 的交接）
=============================================================================
``chunk_source_text`` 在 (D) 滑窗之后，对每个 ``part``：

::

  text          = part                         # 干净正文
  embed_input   = build_embed_text(path, part, tags, heading_path)

然后二选一（由 ``embed`` 参数决定）::

  embed=True   → embed_many(embedder, embed_inputs) → 写入 chunk["vector"]
  embed=False  → 只挂 chunk["embed_input"]；sync 末
                 index_embed.assign_deferred_vectors → 批量 encode（LANE_INDEX）

生产 sync（pgvector）默认 ``embed=False``，避免按文件同步加载/饿死 query；
小路径 / 测试可用 ``embed=True`` 一次做完。模型细节见 ``embedder`` 模块顶注。

=============================================================================
Markdown 四段流水线（非代码分支；「表」= 文内 GFM ``|…|`` 语法，非另文件）
=============================================================================
磁盘上始终是**同一篇** ``.md``；read_file 永远看到完整原文。

::

  ## 人物表                    ← 原文 on disk

  下面是一张 20 行 × 5 列的宽表 …

  | 姓名 | 职务 | … |
  |------|------|---|
  | …    | …    | … |   ← ≥6 行或 ≥800 字符 →「宽表」

  (A) detach_wide_tables → prepared
      宽表换成一行指针；小表原样保留在叙述节中

  (B) split_markdown_sections(prepared)
      按 # / Setext 切节；过短深叶子（<200 字、depth≥4）并入上一节

  (C) iter_wide_table_chunks(**原文**)
      宽表另切：每 8 行线性化为 ``列:值; …`` 独立 TextSection（可检索）

  (D) chunk_split.split_oversized(每节)
      单节 >~450 token → 段/句/词边界滑窗（overlap 64）

  最终 chunks = prose 节经 (D) + 表格节经 (D) 的并集。

双轨 why：叙述节 embedding 不被整表拖脏；表体仍可按单元格语义/词命中。

代码分支（``.py`` / ``.ts`` 等）：符号分节（tree-sitter 优先）→ 同一 (D)，无表双轨。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

# Legacy aliases / fallbacks when settings are unavailable (tests, import order).
# Char fallback ≈ 450 tokens latin (4 char/token); tokenizer path uses max_tokens.
CHUNK_SIZE = 1800
CHUNK_OVERLAP = 200
HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$")
SETEXT_H1_RE = re.compile(r"^=+\s*$")
SETEXT_H2_RE = re.compile(r"^-{3,}\s*$")
_MIN_LEAF_CHARS = 200
_TABLE_ROW_GROUP = 8
# GFM table rows: leading | … |
_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")

SOURCE_SKIP_FILENAMES = frozenset({"paste-debug.md"})

# High-diff path segments used as sparse tags (RQ1c); keep small.
_PATH_TYPE_TAGS = frozenset(
    {
        "persons",
        "periods",
        "dramas",
        "novels",
        "movie",
        "hr",
        "legal",
        "writing",
    }
)
_META_TYPE_RE = re.compile(
    r"^>\s*类型\s*[:：]\s*(\w+)",
    re.IGNORECASE,
)
_META_TAGS_RE = re.compile(
    r"^>\s*tags?\s*[:：]\s*(.+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TextSection:
    """中间分节：尚未滑窗成最终 chunk 的「标题 + 正文」单位。

    English: Intermediate section before ``split_oversized`` expands it into
    one or more chunk dicts. One document yields many TextSections; each may
    become multiple chunks if the body exceeds the token budget.

    字段:
        title: 节标题（Markdown 标题行或代码符号首行）；可为空（前言）。
        body: 节正文（宽表在 prose 路径上可能已是 detach 指针）。
        line_start / line_end: 1-based 行号，映射回磁盘原文。
        heading_path: 从根到当前的标题面包屑，写入 embed 前缀与 tags。
    """

    title: str
    body: str
    line_start: int
    line_end: int
    heading_path: tuple[str, ...] = field(default_factory=tuple)


def should_index_source(path: Path) -> bool:
    """是否纳入 RAG 索引（sources/ 扫描门控）。

    English: Index gate for files under ``sources/``. Does **not** filter by
    suffix here — code under sources/ is chunked via the code branch; watch
    fingerprints may still be suffix-limited (see ``sources_watch``).

    跳过:
        ``paste-debug.md``、dotfile、路径段含 ``cards/``（写作卡片 Turn 内 pin，
        不进检索噪声）。

    参数:
        path: 候选文件 Path。
    返回:
        True 表示可进入 ``chunk_source_text``。
    """
    name = path.name
    if name in SOURCE_SKIP_FILENAMES:
        return False
    if name.startswith("."):
        return False
    # Material cards are pinned into writing turns; keep them out of RAG noise.
    parts = {part.lower() for part in path.parts}
    if "cards" in parts:
        return False
    return True


def path_embed_clue(rel_path: str) -> str:
    """嵌入用语义路径面包屑 ``path: …``（不出现在 citation excerpt）。"""
    p = rel_path.replace("\\", "/").strip("/")
    if p.startswith("sources/"):
        p = p[len("sources/") :]
    for suffix in (".md", ".markdown", ".txt"):
        if p.lower().endswith(suffix):
            p = p[: -len(suffix)]
            break
    return f"path: {p}" if p else ""


def build_embed_text(
    rel_path: str,
    body: str,
    *,
    tags: Sequence[str] | None = None,
    heading_path: Sequence[str] | None = None,
) -> str:
    """组装送入 embedder 的字符串（不是 chunk dict / 不是向量）。

    English: Build the string fed to the embedder. Default keeps citation
    excerpts clean: only heading crumb + body. Optional metadata (path/tags)
    is gated by ``embedding_text_include_metadata``.

    心智模型::

        chunk.text       → 给人看 / BM25 / excerpt（无 path 噪声）
        build_embed_text → 给模型算 384/1024 维稠密向量的*唯一*输入
        embed_many(...)  → list[float]；维数固定，与 body 长短无关

    二者同源 ``part``，但 embed 可多标题面包屑（与可选 path/tags）。
    本函数**不**调用模型；只拼字符串，供同步 embed 或延迟 ``embed_input``。

    参数:
        rel_path: 工作区相对路径（仅 metadata 开启时写入 ``path:`` 前缀）。
        body: 本节/本窗正文 ``part``。
        tags: 稀疏标签；metadata 开启时写成 ``tags: a b``。
        heading_path: ``A > B > C`` 面包屑，始终可前置到 body。
    返回:
        非空时至少含 body 或 crumb；全空则 ``""``。
    """
    body_text = (body or "").strip()
    crumb = " > ".join(str(p).strip() for p in (heading_path or ()) if str(p).strip())
    if crumb:
        body_text = f"{crumb}\n\n{body_text}" if body_text else crumb
    from app.settings import settings

    if not bool(getattr(settings, "embedding_text_include_metadata", False)):
        return body_text

    parts: list[str] = []
    clue = path_embed_clue(rel_path)
    if clue:
        parts.append(clue)
    cleaned_tags = [str(t).strip() for t in (tags or ()) if str(t).strip()]
    if cleaned_tags:
        parts.append("tags: " + " ".join(cleaned_tags))
    if body_text:
        parts.append(body_text)
    return "\n".join(parts)


def extract_source_tags(rel_path: str, text: str, *, max_tags: int = 8) -> list[str]:
    """从路径段与文首 metadata（``> 类型:`` / ``> tags:``）提取高区分 tag，无 LLM。"""
    found: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        tag = raw.strip().lower().replace(" ", "-")
        if not tag or tag in seen:
            return
        # Keep short semantic labels only.
        if len(tag) > 40:
            return
        if any(ch in tag for ch in "（）()[]【】"):
            return
        seen.add(tag)
        found.append(tag)

    for part in rel_path.replace("\\", "/").split("/"):
        stem = part
        for suffix in (".md", ".markdown", ".txt"):
            if stem.lower().endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        if stem.lower() in _PATH_TYPE_TAGS:
            _add(stem.lower())

    header = "\n".join((text or "").splitlines()[:60])
    for line in header.splitlines():
        m_type = _META_TYPE_RE.match(line.strip())
        if m_type:
            _add(m_type.group(1))
            continue
        m_tags = _META_TAGS_RE.match(line.strip())
        if m_tags:
            for piece in re.split(r"[,，、;/|]", m_tags.group(1)):
                _add(piece)

    return found[: max(1, max_tags)]


def _chunk_limits() -> tuple[int, int, int, int]:
    """读取切块预算：``(size_chars, overlap_chars, size_tokens, overlap_tokens)``。

    English: Token budget (~450/64) is an intentional product setting aligned
    with embed ``max_seq≈512`` headroom — **not** the model's theoretical max
    (bge-m3 hub default can be 8192). Char fallback (~1800/200) when no HF
    tokenizer is loaded. Settings unavailable → module-level constants.
    """
    try:
        from app.settings import settings

        size = max(200, int(getattr(settings, "retrieval_chunk_max_chars", CHUNK_SIZE)))
        overlap = max(0, min(size - 1, int(getattr(settings, "retrieval_chunk_overlap_chars", CHUNK_OVERLAP))))
        size_tok = max(64, int(getattr(settings, "retrieval_chunk_max_tokens", 450)))
        ov_tok = max(0, min(size_tok - 1, int(getattr(settings, "retrieval_chunk_overlap_tokens", 64))))
        return size, overlap, size_tok, ov_tok
    except Exception:
        return CHUNK_SIZE, CHUNK_OVERLAP, 450, 64


def _table_detach_thresholds() -> tuple[int, int]:
    try:
        from app.settings import settings

        return (
            max(2, int(settings.retrieval_table_detach_min_rows)),
            max(100, int(settings.retrieval_table_detach_min_chars)),
        )
    except Exception:
        return 6, 800


def _is_table_line(line: str) -> bool:
    s = line.rstrip()
    if not s or not _TABLE_LINE_RE.match(s):
        return False
    return True


def _table_col_count(header_line: str) -> int:
    cells = [c.strip() for c in header_line.strip().strip("|").split("|")]
    return max(1, len([c for c in cells if c is not None]))


def detach_wide_tables(text: str) -> str:
    """宽 GFM 表在 **prepared** 副本中换成短指针（磁盘原文不变）。

    English: Replace wide pipe-tables in the *prepared* copy used for heading
    sectioning. Disk file and ``read_file`` still see the full GFM table.
    Row-level recall is restored by ``iter_wide_table_chunks`` on the **original**
    text (R-4 dual-track).

    「表」指文档正文里的 Markdown 管道表（``| col |``），不是数据库表、不是旁路文件。
    「宽」= 非分隔行 ≥ ``retrieval_table_detach_min_rows``（默认 6）**或**
    块字符数 ≥ ``retrieval_table_detach_min_chars``（默认 800）。小表原样留在叙述节。

    Why: 若整表塞进某一节再 embed，450/512 预算下向量往往只代表表头附近几行，
    表体中间单元格「在库里却几乎不在向量空间」。
    """
    if not text:
        return text
    min_rows, min_chars = _table_detach_thresholds()
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not _is_table_line(line):
            out.append(line)
            i += 1
            continue
        start = i
        while i < len(lines) and _is_table_line(lines[i]):
            i += 1
        block = lines[start:i]
        block_text = "".join(block)
        # Count non-separator rows (header + data).
        data_rows = [
            ln for ln in block if _is_table_line(ln) and not _TABLE_SEP_RE.match(ln.rstrip())
        ]
        row_count = len(data_rows)
        if row_count < min_rows and len(block_text) < min_chars:
            out.extend(block)
            continue
        header = data_rows[0].strip() if data_rows else block[0].strip()
        cols = _table_col_count(header)
        # Preserve newline style of the block end.
        nl = "\n"
        if block and block[-1].endswith("\r\n"):
            nl = "\r\n"
        elif block and block[-1].endswith("\n"):
            nl = "\n"
        pointer = (
            f"[table detached: {row_count} rows × {cols} cols; "
            f"header {header.strip()}; "
            f"full table in source file or sibling under tables/ — see FORMAT]{nl}"
        )
        out.append(pointer)
    return "".join(out)


def _table_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def iter_wide_table_chunks(text: str) -> list[TextSection]:
    """宽表行组 → 独立 TextSection（R-4；读**原文**，不读 prepared）。

    English: Linearize wide tables from the **original** document into separate
    sections so cells remain searchable after prose sections only keep a pointer.

    与 ``detach_wide_tables`` 同阈值；每 ``_TABLE_ROW_GROUP``（8）行数据一批，
    行内 ``列名: 值; …``，批间 `` || `` 连接。标题优先取表前最近 ATX 标题，
    否则取表头首列。产出的 section 再经 ``split_oversized`` 成最终 chunk。
    """
    if not text:
        return []
    min_rows, min_chars = _table_detach_thresholds()
    lines = text.splitlines()
    out: list[TextSection] = []
    i = 0
    caption = ""
    while i < len(lines):
        stripped = lines[i].strip()
        hm = HEADER_RE.match(stripped)
        if hm:
            caption = hm.group(2).strip()
        if not _is_table_line(lines[i]):
            i += 1
            continue
        start = i
        while i < len(lines) and _is_table_line(lines[i]):
            i += 1
        block = lines[start:i]
        data_rows = [
            ln for ln in block if _is_table_line(ln) and not _TABLE_SEP_RE.match(ln.rstrip())
        ]
        block_text = "\n".join(block)
        if len(data_rows) < min_rows and len(block_text) < min_chars:
            continue
        if not data_rows:
            continue
        headers = _table_cells(data_rows[0])
        body_rows = data_rows[1:]
        title = caption or (headers[0] if headers else "table")
        for g in range(0, max(1, len(body_rows)), _TABLE_ROW_GROUP):
            batch = body_rows[g : g + _TABLE_ROW_GROUP]
            linearized: list[str] = []
            for row in batch:
                cells = _table_cells(row)
                pairs = [f"{h}: {c}" for h, c in zip(headers, cells) if c and h]
                if pairs:
                    linearized.append("; ".join(pairs))
            if not linearized:
                continue
            line_start = start + 1 + g
            line_end = min(i, line_start + len(batch) + 1)
            out.append(
                TextSection(
                    title=title,
                    body=f"{title} | " + " || ".join(linearized),
                    line_start=line_start,
                    line_end=line_end,
                    heading_path=(title,),
                )
            )
    return out


def iter_markdown_headings(text: str, *, limit: int = 40) -> list[tuple[int, str]]:
    """返回 ATX/Setext 标题 ``(行号, 标题文本)`` 列表。"""
    lines = text.splitlines()
    found: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = HEADER_RE.match(line)
        if m:
            found.append((i + 1, m.group(2).strip()))
            if len(found) >= limit:
                return found
            i += 1
            continue
        if i + 1 < len(lines) and line.strip() and not line.lstrip().startswith("#"):
            nxt = lines[i + 1]
            if SETEXT_H1_RE.match(nxt) or SETEXT_H2_RE.match(nxt):
                found.append((i + 1, line.strip()))
                if len(found) >= limit:
                    return found
                i += 2
                continue
        i += 1
    return found


def split_markdown_sections(text: str) -> list[TextSection]:
    """按 Markdown 标题切分，并合并过碎的深层叶子节。

    English: Split on ATX (``#``) and Setext headings; maintain ``heading_path``.
    Merge leaves with body <200 chars and heading depth ≥4 into the previous
    section so a lone ``####`` + one sentence does not become a noisy chunk.

    通常吃 ``detach_wide_tables`` 后的 prepared：宽表已是指针，分节向量偏叙述。
    """
    lines = text.splitlines()
    if not lines:
        return []

    sections: list[TextSection] = []
    current_title = ""
    current_path: tuple[str, ...] = ()
    current_lines: list[str] = []
    current_start = 1
    stack: list[tuple[int, str]] = []

    def flush(end_line: int) -> None:
        nonlocal current_title, current_lines, current_start, current_path
        body = "\n".join(current_lines).strip()
        if body or current_title:
            sections.append(
                TextSection(
                    title=current_title,
                    body=body,
                    line_start=current_start,
                    line_end=end_line,
                    heading_path=current_path,
                )
            )
        current_lines = []

    def push_heading(level: int, title: str, line_no: int) -> None:
        nonlocal current_title, current_start, current_path
        flush(line_no - 1 if current_lines or current_title else line_no)
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        current_title = title
        current_path = tuple(t for _, t in stack)
        current_start = line_no

    skip_next = False
    for index, line in enumerate(lines, start=1):
        if skip_next:
            skip_next = False
            continue
        match = HEADER_RE.match(line)
        if match:
            push_heading(len(match.group(1)), match.group(2).strip(), index)
            continue
        if index < len(lines) and line.strip() and not line.lstrip().startswith("#"):
            nxt = lines[index]
            if SETEXT_H1_RE.match(nxt) or SETEXT_H2_RE.match(nxt):
                level = 1 if SETEXT_H1_RE.match(nxt) else 2
                push_heading(level, line.strip(), index)
                skip_next = True
                continue
        current_lines.append(line)

    flush(len(lines))
    return _merge_small_leaves(sections)


def _merge_small_leaves(sections: list[TextSection]) -> list[TextSection]:
    if len(sections) <= 1:
        return sections
    out: list[TextSection] = [sections[0]]
    for sec in sections[1:]:
        if len(sec.body) < _MIN_LEAF_CHARS and len(sec.heading_path) >= 4 and out:
            prev = out[-1]
            extra = sec.body
            if sec.title and sec.title not in extra:
                extra = f"{sec.title}\n{extra}".strip()
            body = prev.body
            if extra:
                body = f"{body}\n\n{extra}".strip() if body else extra
            out[-1] = TextSection(
                title=prev.title,
                body=body,
                line_start=prev.line_start,
                line_end=sec.line_end,
                heading_path=prev.heading_path,
            )
        else:
            out.append(sec)
    return out


def _split_oversized(text: str, *, size: int, overlap: int) -> list[str]:
    """Char-window split kept for tests; production uses ``chunk_split.split_oversized``."""
    from app.retrieval.chunk_split import split_oversized

    return [
        part
        for part, _ in split_oversized(
            text,
            size_chars=size,
            overlap_chars=overlap,
            size_tokens=0,
            overlap_tokens=0,
        )
    ]


# CQ4: light code symbol boundaries (async index path only; no tree-sitter on hot path).
_CODE_EXTS = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".cs",
        ".cpp",
        ".cc",
        ".cxx",
        ".h",
        ".hpp",
        ".c",
        ".rb",
        ".php",
        ".swift",
    }
)
_CODE_SYMBOL_RE = re.compile(
    r"^(?:"
    r"def\s+\w+|async\s+def\s+\w+|class\s+\w+|"  # Python
    r"function\s+\w+|async\s+function\s+\w+|export\s+(?:default\s+)?(?:async\s+)?function\s+\w+|"  # JS
    r"(?:export\s+)?(?:async\s+)?function\s+\w+|export\s+(?:default\s+)?class\s+\w+|"  # TS/JS
    r"func\s+(?:\([^)]*\)\s*)?\w+|type\s+\w+\s+struct\b|"  # Go
    r"(?:pub\s+)?(?:async\s+)?fn\s+\w+|impl(?:\s*<[^>]+>)?\s+\w+|"  # Rust
    r"(?:public|private|protected)?\s*(?:static\s+)?(?:class|interface|enum)\s+\w+"  # Java-ish
    r")",
    re.M,
)


def is_code_path(path: Path | str) -> bool:
    """路径后缀是否走代码分节分支（而非 Markdown 四段流水线）。

    English: True for known source suffixes (``.py``, ``.ts``, …). Chooses
    sectioning inside ``sources/`` only — workspace app code outside ``sources/``
    is never indexed by this module.
    """
    suffix = Path(path).suffix.lower()
    return suffix in _CODE_EXTS


def split_code_sections(text: str, *, language: str | None = None) -> list[TextSection]:
    """按符号边界切分源码（索引平面；优先 tree-sitter，否则 regex）。

    English: Symbol-boundary sections for code under ``sources/``. Prefer
    tree-sitter when ``language`` is known; else ``_CODE_SYMBOL_RE``. Index-only
    — not Locate / ``search_codebase`` (AST+LSP).
    """
    if not text.strip():
        return []
    if language:
        ts_sections = _split_code_sections_treesitter(text, language)
        if ts_sections is not None:
            return ts_sections
    return _split_code_sections_regex(text)


def _split_code_sections_regex(text: str) -> list[TextSection]:
    """Regex-only — safe for async indexing; not a full AST."""
    lines = text.splitlines()
    matches = list(_CODE_SYMBOL_RE.finditer(text))
    if not matches:
        return [
            TextSection(
                title="",
                body=text.strip(),
                line_start=1,
                line_end=text.count("\n") + 1,
            )
        ]

    sections: list[TextSection] = []
    # Preamble before first symbol.
    first_start = matches[0].start()
    if first_start > 0:
        preamble = text[:first_start].rstrip()
        if preamble.strip():
            sections.append(
                TextSection(
                    title="",
                    body=preamble,
                    line_start=1,
                    line_end=preamble.count("\n") + 1,
                )
            )

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].rstrip()
        if not body.strip():
            continue
        title = match.group(0).strip()
        line_start = text[:start].count("\n") + 1
        line_end = line_start + body.count("\n")
        sections.append(
            TextSection(
                title=title,
                body=body,
                line_start=line_start,
                line_end=min(line_end, len(lines)),
            )
        )
    return sections


# tree-sitter node types used as section roots (per language).
_TS_SECTION_TYPES: dict[str, frozenset[str]] = {
    "python": frozenset({"function_definition", "class_definition", "decorated_definition"}),
    "javascript": frozenset(
        {"function_declaration", "class_declaration", "method_definition", "export_statement"}
    ),
    "typescript": frozenset(
        {
            "function_declaration",
            "class_declaration",
            "method_definition",
            "export_statement",
            "interface_declaration",
            "type_alias_declaration",
        }
    ),
    "tsx": frozenset(
        {
            "function_declaration",
            "class_declaration",
            "method_definition",
            "export_statement",
            "interface_declaration",
        }
    ),
    "go": frozenset({"function_declaration", "method_declaration", "type_declaration"}),
    "rust": frozenset({"function_item", "impl_item", "struct_item", "enum_item", "mod_item"}),
    "java": frozenset({"class_declaration", "interface_declaration", "method_declaration", "enum_declaration"}),
}

_EXT_TO_TS_LANG = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}


def language_for_code_path(path: Path | str) -> str | None:
    """由扩展名映射 tree-sitter 语言 id。"""
    return _EXT_TO_TS_LANG.get(Path(path).suffix.lower())


def _split_code_sections_treesitter(text: str, language: str) -> list[TextSection] | None:
    """Return sections from tree-sitter, or None to signal regex fallback."""
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:
        return None
    section_types = _TS_SECTION_TYPES.get(language)
    if not section_types:
        return None
    try:
        parser = get_parser(language)
    except Exception:
        return None
    try:
        tree = parser.parse(text.encode("utf-8"))
    except Exception:
        return None
    root = tree.root_node
    if root is None:
        return None

    lines = text.splitlines()
    # Collect top-level-ish section nodes (direct children of module/program, or decorated).
    nodes = []
    for child in root.children:
        node = child
        if child.type == "decorated_definition" and child.child_count:
            # Prefer the definition inside the decorator wrapper for title extraction.
            for sub in child.children:
                if sub.type in section_types or sub.type in {
                    "function_definition",
                    "class_definition",
                }:
                    node = child  # keep outer span so decorators stay with body
                    break
        if node.type in section_types or (
            node.type == "decorated_definition" and language == "python"
        ):
            nodes.append(node)

    if not nodes:
        return None

    sections: list[TextSection] = []
    # Preamble
    first = nodes[0]
    if first.start_byte > 0:
        preamble = text[: first.start_byte].rstrip()
        if preamble.strip():
            sections.append(
                TextSection(
                    title="",
                    body=preamble,
                    line_start=1,
                    line_end=preamble.count("\n") + 1,
                )
            )

    for index, node in enumerate(nodes):
        start = node.start_byte
        end = nodes[index + 1].start_byte if index + 1 < len(nodes) else len(text.encode("utf-8"))
        # Use byte offsets carefully with utf-8
        body_bytes = text.encode("utf-8")[start:end]
        body = body_bytes.decode("utf-8", errors="replace").rstrip()
        if not body.strip():
            continue
        title = _ts_node_title(node, text)
        line_start = node.start_point[0] + 1
        line_end = line_start + body.count("\n")
        sections.append(
            TextSection(
                title=title,
                body=body,
                line_start=line_start,
                line_end=min(line_end, len(lines)),
            )
        )
    return sections or None


def _ts_node_title(node, text: str) -> str:
    """First non-empty line of the node, truncated."""
    start = node.start_byte
    end = min(node.end_byte, start + 200)
    snippet = text.encode("utf-8")[start:end].decode("utf-8", errors="replace")
    for line in snippet.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return node.type


def split_code_sections_legacy(text: str) -> list[TextSection]:
    """测试用别名：仅 regex 分节。"""
    return _split_code_sections_regex(text)


def chunk_source_text(
    path: Path,
    rel_path: str,
    text: str,
    *,
    embedder,
    tags: Sequence[str] | None = None,
    embed: bool = True,
) -> list[dict[str, Any]]:
    """将**单个**源文件切为 chunk 字典列表（一篇文档 → N 条记录）。

    English: One file → many chunk dicts. Document size does not switch strategy:
    small files yield few chunks; large files yield many. Each chunk's *text*
    targets ≤~450 tokens; each *vector* is always the embedder's fixed dim
    (384/1024/…). Short text still produces a dense vector — narrower semantics,
    not fewer dimensions.

    分支:
        - 代码后缀 → ``split_code_sections`` → (D) ``split_oversized``
        - 其它（典型 ``.md`` / ``.txt``）→ (A)(B)+(C) → (D)；见模块顶流水线

    参数:
        path: 磁盘 Path（mtime / stem / 扩展名）。
        rel_path: 工作区相对路径（写入 ``path`` / ``chunk_id``）。
        text: 文件全文（UTF-8 已解码）。
        embedder: ``embed=True`` 时传入 ``get_embedder()`` 供 ``embed_many``；
            延迟路径可传占位 / ``None``（仅拼 ``embed_input``）。
        tags: 覆盖标签；``None`` 时 ``extract_source_tags``。
        embed: True → 写 ``vector``（同步 encode）；
            False → 写 ``embed_input``，交 ``index_embed.assign_deferred_vectors``。

    返回:
        chunk dict 列表。关键键：``chunk_id``, ``path``, ``text``, ``citation_id``,
        ``section_title``, ``line_start``, ``line_end``, ``mtime``；可选 ``tags``,
        ``symbol``, ``vector`` / ``embed_input``。空文件 → ``[]``。

    不变量:
        - 不修改磁盘原文（detach 仅作用于内存 prepared）。
        - ``text`` 不含 path 前缀（引用摘录干净）；向量输入经 ``build_embed_text``。
        - 进模型的是字符串列表，不是 chunk JSON；维数由 embedder 决定。
    """
    if not text.strip():
        return []

    # Index-time only: wide tables become pointers; disk file unchanged for read_file.
    # CQ4: code files use symbol boundaries; markdown keeps heading/table path.
    if is_code_path(path) or is_code_path(rel_path):
        prepared = text
        sections = split_code_sections(
            prepared,
            language=language_for_code_path(path) or language_for_code_path(rel_path),
        )
    else:
        # Markdown / prose pipeline (four stages — see module docstring):
        #
        #   original text on disk
        #        │
        #        ├─► (A) detach_wide_tables ──► prepared (wide tables → pointers)
        #        │         │
        #        │         └─► (B) split_markdown_sections ──► prose TextSections
        #        │
        #        └─► (C) iter_wide_table_chunks(original) ──► table TextSections
        #                  (8-row batches, header: cell linearized)
        #
        #   sections = (B) + (C)  →  each section ──► (D) chunk_split.split_oversized
        #                  (~450 tok / 64 overlap, paragraph/sentence snap)
        #
        # Why dual-track: (A) keeps section embeddings about narrative;
        # (C) still makes row-level facts searchable without one giant table vector.
        prepared = detach_wide_tables(text)
        sections = split_markdown_sections(prepared)
        extra = iter_wide_table_chunks(text)
        if extra:
            sections = list(sections) + extra
    if not sections:
        sections = [
            TextSection(
                title="",
                body=prepared.strip(),
                line_start=1,
                line_end=prepared.count("\n") + 1,
            )
        ]

    chunk_size, chunk_overlap, size_tokens, overlap_tokens = _chunk_limits()
    from app.retrieval.chunk_split import split_oversized as _split_payload

    chunks: list[dict[str, Any]] = []
    embed_inputs: list[str] = []
    chunk_idx = 0
    if tags is None:
        tag_list = extract_source_tags(rel_path, text)
    else:
        tag_list = [str(t).strip() for t in tags if str(t).strip()]
    # Code: add filename stem + language as sparse tags for retrieval.
    if is_code_path(path) or is_code_path(rel_path):
        stem = Path(rel_path).stem
        lang = Path(rel_path).suffix.lstrip(".").lower()
        for extra in (stem, lang, "code"):
            if extra and extra not in tag_list:
                tag_list.append(extra)
    for section in sections:
        section_text = section.body.strip()
        if not section_text and not section.title:
            continue
        payload = section_text
        if section.title and section.title not in section_text:
            payload = f"{section.title}\n{section_text}".strip()
        if not payload:
            continue

        heading_path = tuple(section.heading_path or (() if not section.title else (section.title,)))
        section_tags = list(tag_list)
        for crumb in heading_path:
            if crumb and crumb not in section_tags:
                section_tags.append(crumb[:40])

        # (D) Section longer than ~450 tokens → sliding windows with overlap.
        # Short sections pass through as a single (part, 0) — still one full-dim vector.
        for part, origin in _split_payload(
            payload,
            size_chars=chunk_size,
            overlap_chars=chunk_overlap,
            size_tokens=size_tokens,
            overlap_tokens=overlap_tokens,
        ):
            chunk_id = f"{rel_path}#chunk-{chunk_idx}"
            line_start = section.line_start + payload[:origin].count("\n")
            line_end = line_start + part.count("\n")
            # Embed handoff (index-time only — search never re-chunks):
            #   part  → chunk["text"]          (BM25 / excerpt / cites)
            #   part  → build_embed_text(...)  (model input string, may add crumb)
            # Then either vector now (embed=True) or embed_input later (False).
            embed_input = build_embed_text(
                rel_path, part, tags=section_tags, heading_path=heading_path
            )
            chunk: dict[str, Any] = {
                "chunk_id": chunk_id,
                "path": rel_path,
                "citation_id": f"cite:{path.stem}",
                "section_title": section.title,
                "line_start": line_start,
                "line_end": line_end,
                # Display / BM25 / excerpt — body only (no path noise in cites).
                "text": part,
                "mtime": path.stat().st_mtime,
            }
            if section_tags:
                chunk["tags"] = list(section_tags)
            if section.title:
                chunk["symbol"] = section.title
            chunks.append(chunk)
            embed_inputs.append(embed_input)
            chunk_idx += 1

    if not chunks:
        return []
    if embed:
        from app.retrieval.embedder import embed_many

        # Synchronous path: one batch encode for this file's strings.
        # len(vector) == embedder dim for every chunk (short or long);
        # ST uses normalize_embeddings=True (see embedder.SentenceTransformerEmbedder).
        vectors = embed_many(embedder, embed_inputs)
        for chunk, vec in zip(chunks, vectors, strict=True):
            chunk["vector"] = vec
    else:
        # Deferred path (pgvector sync default): stash strings for
        # index_embed.assign_deferred_vectors → embed_many(..., lane=LANE_INDEX).
        for chunk, embed_input in zip(chunks, embed_inputs, strict=True):
            chunk["embed_input"] = embed_input
    return chunks
