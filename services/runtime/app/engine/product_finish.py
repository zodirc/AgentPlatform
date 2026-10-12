"""产品模式收尾：代跑一条测试、注入 diff、一次只读审阅。评测模式不进入。"""

from __future__ import annotations

from typing import Any


def product_mode(state: Any) -> bool:
    from app.tenant_context import current_ops_eval

    if bool(getattr(state, "ops_eval", False)) or current_ops_eval():
        return False
    if str(getattr(state, "scenario_id", "") or "") != "agent":
        return False
    return True


def one_related_command(state: Any) -> str:
    related = list(getattr(state, "related_tests_union", None) or [])
    chosen = ""
    best = -1
    for item in related:
        if isinstance(item, dict):
            command = str(item.get("command") or "").strip()
            score = len(str(item.get("path") or ""))
        elif isinstance(item, str):
            command = item.strip()
            score = 0
        else:
            continue
        if command and score >= best:
            chosen = command
            best = score
    return chosen


async def run_product_verify_hook(state: Any) -> dict[str, Any] | None:
    """``verify_pending`` 时在沙箱里跑最具体的一条相关测试。每 Turn 一次。"""
    from app.settings import settings

    if not product_mode(state):
        return None
    if not bool(getattr(settings, "product_post_edit_hook", True)):
        return None
    if getattr(state, "product_hook_ran", False):
        return None
    if not getattr(state, "verify_pending", False):
        return None
    command = one_related_command(state)
    if not command:
        return None
    state.product_hook_ran = True
    from app.tools.core.edit_tools import run_tests

    result = await run_tests(command=command, turn_id=getattr(state, "turn_id", None))
    if isinstance(result, dict):
        result["product_hook"] = True
    return result if isinstance(result, dict) else None


def work_diff_stat(state: Any) -> str:
    """``git diff --stat`` 加未跟踪文件。``.agent/scratch/`` 不列出。"""
    import subprocess

    from app.tenant_context import current_work_root_path

    try:
        root = current_work_root_path()
    except Exception:
        return ""
    if not (root / ".git").exists():
        return ""
    try:
        stat = subprocess.run(
            ["git", "diff", "--stat", "--", ".", ":(exclude).agent/scratch"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "--", ".", ":(exclude).agent/scratch"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    lines = [stat.stdout.strip()]
    extras = [
        line.strip()
        for line in untracked.stdout.splitlines()
        if line.strip() and not line.strip().startswith(".agent/scratch/")
    ]
    if extras:
        shown = extras[:30]
        lines.append("未跟踪：")
        lines.extend(f"  {item}" for item in shown)
        if len(extras) > len(shown):
            lines.append(f"  …另有 {len(extras) - len(shown)} 个")
        lines.append("临时复现脚本放在 .agent/scratch/，不进 diff；交卷前请清理。")
    text = "\n".join(line for line in lines if line).strip()
    return text[:4000]


def acceptance_plan_items(message: str) -> list[dict[str, str]]:
    """从用户消息的围栏和「验收」行抽出计划项。命令写在标题里，事件 schema 不带额外字段。"""
    import re

    text = message or ""
    items: list[dict[str, str]] = []
    for index, body in enumerate(re.findall(r"```[^\n]*\n(.*?)```", text, flags=re.S)):
        snippet = " ".join(body.strip().split())[:180]
        if not snippet:
            continue
        items.append(
            {
                "id": f"accept-{index + 1}",
                "title": f"验收：{snippet}"[:512],
                "status": "pending",
                "acceptance": snippet[:300],
            }
        )
        if len(items) >= 6:
            break
    if len(items) < 6:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("验收") and len(stripped) > 2:
                command = stripped.split("：", 1)[-1].split(":", 1)[-1].strip()[:180]
                if not command:
                    continue
                items.append(
                    {
                        "id": f"accept-{len(items) + 1}",
                        "title": f"验收：{command}"[:512],
                        "status": "pending",
                        "acceptance": command[:300],
                    }
                )
            if len(items) >= 6:
                break
    return items


def acceptance_gap(state: Any) -> str:
    commands = [str(item).strip() for item in (getattr(state, "acceptance_commands", None) or []) if str(item).strip()]
    if not commands:
        return ""
    last = str(getattr(state, "last_test_command", "") or "").strip()
    pending = getattr(state, "verify_pending", False)
    missing = [cmd for cmd in commands if cmd != last or pending]
    if not missing:
        return ""
    return "计划验收尚未在最近一次编辑后跑通：" + "；".join(missing[:3])
