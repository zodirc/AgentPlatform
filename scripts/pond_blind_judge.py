#!/usr/bin/env python3
"""离线三层盲测评委。只进 Ops lab，禁止产品 Turn 调用。

输入两本候选的「这本书」+「开篇」原文（遮去书名与所有标签）。
有 WRITING_POND_JUDGE_CMD 时才调 LLM；默认打印提示，不调用。
与人眼抽样一致率 ≥ 0.8 后才可用于扩样统计。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_APP = ROOT / "services" / "runtime"
if str(RUNTIME_APP) not in sys.path:
    sys.path.insert(0, str(RUNTIME_APP))

from app.writing.narrative.judge import _JSON_FENCE  # noqa: E402

JUDGE_SYSTEM = """你是开篇候选盲测评委，不是写作教练。只根据给定正文判断。
两本材料都已经遮去书名和所有轴/自述标签。只看「这本书」和「开篇」。
规则：
- 换名词（地铁/窗口/协会/管理局/登记/配额只是换叫法）= 同一世界。
- 一个在医院一个在拳场，但都是普通人靠异常资格钻规则 = 同一冲突机制。
- 各自推到第 200 章若都是「升级 → 接任务 → 更大组织」= 同一长篇形状。
输出一个 JSON 对象，不要解释，不要 markdown：
{"same_world": 0或1, "same_conflict_engine": 0或1, "same_ch200": 0或1, "why": "不超过60字"}
"""


def judge_user_prompt(left: str, right: str) -> str:
    return (
        "候选 A：\n"
        + left.strip()[:4000]
        + "\n\n候选 B：\n"
        + right.strip()[:4000]
        + "\n\n只输出 JSON。"
    )


def parse_blind_payload(raw: str) -> dict[str, object]:
    blob = (raw or "").strip()
    if not blob:
        raise ValueError("empty_judge")
    match = _JSON_FENCE.search(blob)
    if match:
        blob = match.group(1).strip()
    start = blob.find("{")
    end = blob.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("judge_not_json")
    data = json.loads(blob[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("judge_not_object")
    out = {
        "same_world": 1 if int(data.get("same_world") or 0) else 0,
        "same_conflict_engine": 1 if int(data.get("same_conflict_engine") or 0) else 0,
        "same_ch200": 1 if int(data.get("same_ch200") or 0) else 0,
        "why": str(data.get("why") or "")[:60],
    }
    return out


def _run_cmd(cmd: str, prompt: str) -> str:
    proc = subprocess.run(
        cmd,
        input=JUDGE_SYSTEM + "\n\n" + prompt,
        text=True,
        capture_output=True,
        check=False,
        shell=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or f"judge cmd failed: {proc.returncode}")
    return proc.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", required=True, help="候选 A：这本书 + 开篇")
    parser.add_argument("--right", required=True, help="候选 B：这本书 + 开篇")
    parser.add_argument(
        "--cmd",
        default=os.environ.get("WRITING_POND_JUDGE_CMD", ""),
        help="评委命令；空则只打印提示",
    )
    args = parser.parse_args(argv)
    prompt = judge_user_prompt(args.left, args.right)
    if not args.cmd:
        print(JUDGE_SYSTEM)
        print(prompt)
        return 0
    raw = _run_cmd(args.cmd, prompt)
    print(json.dumps(parse_blind_payload(raw), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
