"""工作区约定文件（AGENT.md 等）加载与 per-step runtime_context 软提示。"""

from __future__ import annotations


import time
from pathlib import Path
from uuid import UUID

from app.settings import settings

_PROJECT_FILES = ("AGENT.md", "agent.md", "outline.md", "AGENTS.md", "CLAUDE.md")
_CACHE_MAX = 256
_CACHE_TTL_S = 3600.0
# key → (text, expires_monotonic)
_session_project_cache: dict[str, tuple[str, float]] = {}


def _purge_project_cache() -> None:
    now = time.monotonic()
    expired = [k for k, (_, exp) in _session_project_cache.items() if exp <= now]
    for key in expired:
        _session_project_cache.pop(key, None)
    overflow = len(_session_project_cache) - _CACHE_MAX
    if overflow <= 0:
        return
    oldest = sorted(_session_project_cache.items(), key=lambda kv: kv[1][1])[:overflow]
    for key, _ in oldest:
        _session_project_cache.pop(key, None)


def load_project_context(*, session_id: UUID | str | None = None, scenario_id: str | None = None) -> str:
    """作用：加载 AGENT.md 等约定文件（session 缓存）。编码场景不把 outline.md 当规则。"""
    key = f"{session_id if session_id is not None else '_default'}:{scenario_id or ''}"
    _purge_project_cache()
    cached = _session_project_cache.get(key)
    if cached is not None:
        return cached[0]

    root = Path(settings.workspace_root)
    chunks: list[str] = []
    budget = max(200, settings.project_context_max_chars)
    used = 0
    for name in _PROJECT_FILES:
        if scenario_id == "agent" and name == "outline.md":
            continue
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        remaining = budget - used
        if remaining <= 0:
            break
        snippet = text[:remaining]
        chunks.append(f"## {name}\n{snippet}")
        used += len(snippet)
    result = "\n\n".join(chunks)
    rules = _always_apply_rules(root, budget=max(0, budget - used))
    if rules:
        result = f"{result}\n\n{rules}".strip() if result else rules
    _session_project_cache[key] = (result, time.monotonic() + _CACHE_TTL_S)
    return result


def clear_project_context_cache(session_id: UUID | str | None = None) -> None:
    """作用：清除 project 文件缓存。"""
    if session_id is None:
        _session_project_cache.clear()
        return
    _session_project_cache.pop(str(session_id), None)


def build_runtime_context(
    *,
    scenario_id: str,
    step_count: int,
    max_steps: int,
    model_name: str | None = None,
    plan_hint: str | None = None,
) -> str:
    """作用：构造 per-step 软预算 runtime_context 字符串。"""
    parts = [
        f"scenario_id={scenario_id}",
        f"step={step_count}/{max_steps}",
        f"steps_remaining={max(0, max_steps - step_count)}",
    ]
    if model_name:
        parts.append(f"model={model_name}")
    text = "[runtime_context] " + " ".join(parts)
    if plan_hint:
        text = f"{text}\n[plan_hint] {plan_hint}"
    return text


def workset_block(state: object) -> str:
    """本步附在 volatile 上的工作集，不超过 600 字。"""
    from app.policy.shadow_git import reverted_paths

    files = list(getattr(state, "edited_files", None) or [])
    pending = bool(getattr(state, "verify_pending", False))
    failure = str(getattr(state, "last_test_first_failure", "") or "").strip()
    hint = str(getattr(state, "plan_hint", "") or "").strip()
    last_cmd = str(getattr(state, "last_test_command", "") or "").strip()
    delta = getattr(state, "last_test_delta", None) or {}
    parts: list[str] = []
    if files:
        shown = []
        for row in files[:8]:
            path = str(row.get("path") or "")
            shown.append(f"{path} +{row.get('added', 0)}/-{row.get('removed', 0)}")
        parts.append("已改 " + "，".join(shown))
    elif int(getattr(state, "code_edits_since_verify", 0) or 0):
        parts.append(f"本轮已改代码文件 {int(getattr(state, 'code_edits_since_verify', 0) or 0)} 个")
    if pending:
        unverified = [str(row.get("path") or "") for row in files if row.get("path")]
        if unverified:
            parts.append("未验证 " + "，".join(unverified[:6]))
        else:
            parts.append("未验证")
    if last_cmd:
        parts.append(f"最近测试 {last_cmd[:80]}")
    if isinstance(delta, dict) and delta:
        parts.append(
            "delta "
            + ",".join(
                f"{key}={len(delta.get(key) or [])}"
                for key in ("newly_failing", "newly_passing", "still_failing")
                if delta.get(key)
            )
        )
    reverted = reverted_paths()
    if reverted:
        parts.append("用户已撤销 " + "，".join(reverted[:4]))
    if failure:
        first = failure.splitlines()[0][:120]
        parts.append(f"最近失败：{first}")
    if hint:
        parts.append(f"计划：{hint[:80]}")
    items = list(getattr(state, "plan_items", None) or [])
    if items:
        done = sum(1 for item in items if str(item.get("status") or "") in {"done", "completed"})
        parts.append(f"计划：{done}/{len(items)} 完成")
    offer = str(getattr(state, "command_offer", "") or "").strip()
    if offer:
        parts.append(offer[:160])
    return "；".join(part for part in parts if part)[:600]


def fold_loaded_rules(text: str, *, limit: int = 12_000) -> str:
    """规则块过大时收成一行。去掉标记后，下次碰到该路径会重新展开。"""
    import re

    body = text or ""
    if len(body) <= limit or "<!-- rules:" not in body:
        return body
    folded = re.sub(
        r"<!-- rules:(.+?) -->\n.*?(?=\n<!-- rules:|\Z)",
        lambda match: f"规则 {match.group(1).rsplit('/', 1)[-1]} 已加载（{match.group(1).strip()}）",
        body,
        flags=re.S,
    )
    return folded.strip()


def append_agents_command(root: Path, command: str) -> dict[str, str]:
    """把用户确认过的测试或构建命令写进 AGENTS.md。同一行不重复写。"""
    text = " ".join(str(command or "").split())
    if not text or len(text) > 200 or any(ch in text for ch in "\n\r`"):
        raise ValueError("command rejected")
    path = root / "AGENTS.md"
    body = path.read_text(encoding="utf-8") if path.is_file() else "# AGENTS\n"
    line = f"- `{text}`"
    if line in body:
        return {"status": "present", "path": "AGENTS.md"}
    start = "<!-- agent:commands -->"
    end = "<!-- /agent:commands -->"
    if start not in body or end not in body:
        body = body.rstrip() + f"\n\n{start}\n{line}\n{end}\n"
    else:
        body = body.replace(end, f"{line}\n{end}", 1)
    path.write_text(body, encoding="utf-8")
    return {"status": "written", "path": "AGENTS.md"}


def append_path_rules(state: object, rel_path: str) -> None:
    """读或改某路径时，把该路径上的目录规则追加进 volatile_context。"""
    block = _rules_for_relative_path(rel_path)
    if not block:
        return
    marker = f"<!-- rules:{rel_path.strip()} -->"
    current = str(getattr(state, "volatile_context", "") or "")
    if marker in current:
        return
    extra = f"{marker}\n{block}"
    if len(current) + len(extra) > 24_000:
        return
    updated = f"{current}\n\n{extra}".strip() if current else extra
    try:
        setattr(state, "volatile_context", updated)
    except Exception:
        return


def _always_apply_rules(root: Path, *, budget: int) -> str:
    if budget <= 0:
        return ""
    rules_dir = root / ".cursor" / "rules"
    if not rules_dir.is_dir():
        return ""
    chunks: list[str] = []
    used = 0
    for path in sorted(rules_dir.glob("*.mdc")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not _frontmatter_flag(text, "alwaysApply"):
            continue
        remaining = budget - used
        if remaining <= 0:
            break
        snippet = text[:remaining]
        chunks.append(f"## {path.name}\n{snippet}")
        used += len(snippet)
    return "\n\n".join(chunks)


def _rules_for_relative_path(rel_path: str) -> str:
    from app.tenant_context import current_work_root_path

    try:
        root = current_work_root_path()
    except Exception:
        root = Path(settings.workspace_root)
    normalized = rel_path.strip().lstrip("/").replace("\\", "/")
    if not normalized or normalized.startswith(".."):
        return ""
    directory = (root / normalized).parent
    chunks: list[str] = []
    seen: set[Path] = set()
    cursor = directory
    while True:
        try:
            cursor.relative_to(root)
        except ValueError:
            break
        if cursor != root:
            for name in ("AGENTS.md", "CLAUDE.md"):
                path = cursor / name
                if path in seen or not path.is_file():
                    continue
                seen.add(path)
                try:
                    text = path.read_text(encoding="utf-8", errors="replace").strip()
                except OSError:
                    continue
                if text:
                    chunks.append(f"## {path.relative_to(root).as_posix()}\n{text[:2000]}")
        if cursor == root:
            break
        cursor = cursor.parent
    rules_dir = root / ".cursor" / "rules"
    if rules_dir.is_dir():
        for path in sorted(rules_dir.glob("*.mdc")):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _frontmatter_flag(text, "alwaysApply"):
                continue
            if _globs_match(text, normalized):
                chunks.append(f"## {path.name}\n{text.strip()[:2000]}")
    return "\n\n".join(chunks)[:8000]


def _frontmatter_flag(text: str, key: str) -> bool:
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end < 0:
        return False
    head = text[3:end]
    return f"{key}: true" in head or f"{key}:true" in head


def _globs_match(text: str, rel_path: str) -> bool:
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end < 0:
        return False
    head = text[3:end]
    for raw in head.splitlines():
        if "globs" not in raw:
            continue
        pattern = raw.split(":", 1)[-1].strip().strip("\"'")
        if pattern.startswith("**/"):
            pattern = pattern[3:]
        if pattern.startswith("*."):
            if rel_path.endswith(pattern[1:]):
                return True
        elif pattern and (rel_path == pattern or rel_path.endswith("/" + pattern)):
            return True
    return False
