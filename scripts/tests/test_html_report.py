"""html_report: Chinese labels + evaluation flow section."""

from __future__ import annotations

import json
from pathlib import Path

from official_bench.html_report import (
    flow_steps_for_suite,
    status_zh,
    suite_zh,
    write_html_report,
)


def test_status_and_suite_zh() -> None:
    assert status_zh("pass") == "通过"
    assert status_zh("completed") == "已完成"
    assert suite_zh("coding") == "编码（SWE-bench Lite）"


def test_coding_flow_includes_harness_branch() -> None:
    steps = flow_steps_for_suite("coding", eval_path="agent", coding_harness=False)
    titles = [t for t, _ in steps]
    assert "拉取 SWE-bench Lite" in titles
    assert "跳过 Harness" in titles
    assert "生成报告" in titles


def test_write_html_report_chinese_and_flow(tmp_path: Path) -> None:
    manifest = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "SWE-bench Lite · 单测样例",
        "official_suite": "coding",
        "status": "completed",
        "created_at": "2026-08-13T00:00:00+00:00",
        "finished_at": "2026-08-13T00:01:00+00:00",
        "summary": {"total": 1, "pass": 1, "fail": 0, "skipped": 0},
        "metrics": {"patch_rate": 1.0, "resolve_rate": 0.0},
        "model_meta": {"eval_path": "agent", "harness": False},
        "cases": [
            {
                "case_id": "repo__x-1",
                "status": "pass",
                "bucket": "patch_no_apply",
                "metrics": {"ok": 1},
                "error": None,
            }
        ],
        "logs": [
            {
                "at": "2026-08-13T00:00:01+00:00",
                "kind": "run_started",
                "message": "start",
            }
        ],
    }
    out = tmp_path / "report.html"
    write_html_report(out, manifest)
    html = out.read_text(encoding="utf-8")
    assert "lang=\"zh-CN\"" in html
    assert "本次评测流程" in html
    assert "用例总数" in html
    assert "通过" in html
    assert "补丁产出率" in html
    assert "产品 Turn 改码" in html
    assert "跳过 Harness" in html
    assert "开始" in html  # kind_zh(run_started)
    assert json.dumps({"ok": 1}) not in html or "ok" in html
