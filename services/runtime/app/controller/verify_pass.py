"""确定性引用校验（docs/13 S3 A4）：扫草稿 cite/路径，写报告，不改稿。

仅用户/离线触发；遍历 exports、sections、session revisions 等近期 md，
核对 cite: 与 sources/|sections/ 路径是否存在于当前 work_root。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.settings import settings
from app.tools.validate import extract_citation_ids

_REF_PATH_RE_IMPORT = None


def _ref_path_re():
    """懒编译引用路径正则（支持 CJK 文件名）。

    返回:
        匹配 ``sources|sections/...``.md|txt|markdown 的 Pattern。
    """
    import re

    global _REF_PATH_RE_IMPORT
    if _REF_PATH_RE_IMPORT is None:
        # Paths may include CJK filenames.
        _REF_PATH_RE_IMPORT = re.compile(
            r"(?:sources|sections)/[^\s\]\[<>\"'`，。；;]+\.(?:md|txt|markdown)\b"
        )
    return _REF_PATH_RE_IMPORT


def _workspace() -> Path:
    """当前租户 work_root；无 TenantContext 时回退 settings.workspace_root。

    返回:
        解析后的绝对 Path。
    """
    try:
        from app.tenant_context import current_work_root_path

        return current_work_root_path()
    except Exception:
        return Path(settings.workspace_root).resolve()


def _iter_draft_texts(root: Path) -> list[tuple[str, str]]:
    """收集待校验草稿：相对路径 + 正文。

    优先最近修改的文件（最多 120），使 verify 命中最新写作轮次。

    参数:
        root: work_root。

    返回:
        ``(rel_path, text)`` 列表。
    """
    candidates: list[Path] = []
    for rel in ("exports", "sections"):
        base = root / rel
        if base.is_dir():
            candidates.extend(p for p in base.rglob("*.md") if p.is_file())
    sessions = root / ".agent" / "sessions"
    if sessions.is_dir():
        candidates.extend(
            p
            for p in sessions.rglob("*.md")
            if p.is_file() and "revisions" in p.relative_to(sessions).parts
        )
    legacy_revisions = root / ".agent" / "revisions"
    if legacy_revisions.is_dir():
        candidates.extend(p for p in legacy_revisions.rglob("*.md") if p.is_file())
    # Prefer recently modified drafts so verify hits the latest writing turn.
    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    texts: list[tuple[str, str]] = []
    for path in candidates[:120]:
        try:
            texts.append(
                (
                    str(path.relative_to(root)),
                    path.read_text(encoding="utf-8", errors="replace"),
                )
            )
        except OSError:
            continue
    return texts


def _source_exists(root: Path, citation_id: str) -> bool:
    """判断 cite id 是否在 sources/ 下有对应文件或正文命中。

    参数:
        root: work_root。
        citation_id: 原始或 ``cite:`` 前缀形式。

    返回:
        找到匹配则为 True。
    """
    stem = citation_id.replace("cite:", "").strip()
    sources = root / "sources"
    if not sources.is_dir() or not stem:
        return False
    for fp in sources.rglob("*"):
        if not fp.is_file():
            continue
        name = fp.name
        if stem in name or stem in str(fp.relative_to(root)):
            return True
        # Also accept stem without extension match (亮剑 ↔ 亮剑.md).
        if fp.stem == stem:
            return True
        try:
            # 最后才读全文：路径/文件名未命中时用正文包含兜底。
            if stem in fp.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


def scan_text_citations(text: str) -> list[str]:
    """HM7：扫描单段 markdown，返回可读的引用/路径问题列表。

    参数:
        text: markdown 正文。

    返回:
        如 ``unverified_citation: ...`` / ``missing_path: ...`` 的字符串列表。
    """
    root = _workspace()
    issues: list[str] = []
    path_re = _ref_path_re()
    cites = extract_citation_ids(text)
    for cite in cites:
        ok = _source_exists(root, cite)
        if not ok:
            label = cite if cite.startswith("cite:") else f"cite:{cite}"
            issues.append(f"unverified_citation: {label}")
    for path in sorted(set(path_re.findall(text))):
        if not (root / path).is_file():
            issues.append(f"missing_path: {path}")
    return issues


def run_verify_pass(*, session_id: str | None = None) -> dict[str, Any]:
    """跑完整 verify：扫草稿、写 ``.agent/verify-reports/``，不改 draft。

    参数:
        session_id: 可选，写入报告元数据。

    返回:
        含 status / checked / invalid / findings / report_path / summary /
        ``mutated_draft=False`` 的结果 dict。
    """
    root = _workspace()
    findings: list[dict[str, Any]] = []
    checked = 0
    path_re = _ref_path_re()
    for rel, text in _iter_draft_texts(root):
        cites = extract_citation_ids(text)
        paths = sorted(set(path_re.findall(text)))
        for cite in cites:
            checked += 1
            ok = _source_exists(root, cite)
            findings.append(
                {
                    "file": rel,
                    "citation_id": cite if cite.startswith("cite:") else f"cite:{cite}",
                    "valid": ok,
                }
            )
        for path in paths:
            checked += 1
            ok = (root / path).is_file()
            findings.append({"file": rel, "path": path, "valid": ok})

    invalid = [f for f in findings if not f.get("valid")]
    lines = [
        "# Verify report",
        "",
        f"- generated_at: {datetime.now(UTC).isoformat()}",
        f"- session_id: {session_id or '-'}",
        f"- checked: {checked}",
        f"- invalid: {len(invalid)}",
        "",
    ]
    if invalid:
        lines.append("## Issues")
        for item in invalid[:50]:
            lines.append(f"- `{item}`")
        lines.append("")
    else:
        lines.append("No citation/path issues found in drafts/exports.")
        lines.append("")

    report_dir = root / ".agent" / "verify-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"verify-{stamp}.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    rel_report = str(report_path.relative_to(root))
    summary = (
        f"Verify complete: checked={checked}, invalid={len(invalid)}; "
        f"report={rel_report}"
    )
    return {
        "status": "completed",
        "checked": checked,
        "invalid": len(invalid),
        "findings": findings[:100],
        "report_path": rel_report,
        "summary": summary,
        "mutated_draft": False,
    }
