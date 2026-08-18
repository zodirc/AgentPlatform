from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.tools.core.kb_audit import (
    audit_knowledge_base,
    parse_rules,
    scan_articles,
    scan_paths,
)

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "eval" / "0112" / "data"


def test_parse_rules_from_fixture() -> None:
    md = (DATA / "business_context.md").read_text(encoding="utf-8")
    rules = parse_rules(md)
    assert rules["no_reason_days"] == 7
    assert rules["cod_forbidden"] is True
    assert rules["silver_spend"] == 2000
    assert rules["coupon_stack"] is False
    assert "中通" in rules["couriers"]


def test_scan_fixture_catches_planted_issues_not_ids() -> None:
    result = scan_paths(DATA / "kb_articles.json", DATA / "business_context.md")
    articles = json.loads((DATA / "kb_articles.json").read_text(encoding="utf-8"))
    by_id = {a["id"]: a for a in articles}

    empty_ids = {f["id"] for f in result["findings"] if f["type"] == "empty"}
    assert {a["id"] for a in articles if not str(a.get("answer") or "").strip()} <= empty_ids
    assert "KB032" in empty_ids
    assert "KB037" in empty_ids

    stale = [f for f in result["findings"] if f["type"] == "stale_conflict"]
    stale_ids = {f["id"] for f in stale}
    assert any("货到付款" in by_id[i]["answer"] and i in stale_ids for i in stale_ids)
    assert "KB008" in stale_ids
    assert "KB012" in stale_ids
    assert "KB014" in stale_ids
    assert "KB015" in stale_ids
    assert "KB016" in stale_ids

    dup_ids = {f["id"] for f in result["findings"] if f["type"] == "dup_question"}
    assert {"KB001", "KB039"} <= dup_ids

    intra_ids = {f["id"] for f in result["findings"] if f["type"] == "intra_conflict"}
    assert "KB001" in intra_ids
    assert "KB002" in intra_ids

    flagged = set(result["flagged_ids"])
    assert "KB009" not in flagged
    assert "KB031" not in flagged
    assert "KB038" not in flagged
    assert "KB020" not in stale_ids

    topics = {g["topic"] for g in result["coverage_gaps"]}
    assert "邮件客服" in topics


def test_scan_does_not_hardcode_article_ids_in_detectors() -> None:
    src = (REPO / "services" / "runtime" / "app" / "tools" / "core" / "kb_audit.py").read_text(
        encoding="utf-8"
    )
    for kid in ("KB008", "KB032", "KB039", "KB012"):
        assert kid not in src


@pytest.mark.asyncio
async def test_audit_tool_writes_report(workspace: Path) -> None:
    kb = workspace / "sources" / "kb"
    kb.mkdir(parents=True)
    (kb / "kb_articles.json").write_text(
        (DATA / "kb_articles.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (kb / "business_context.md").write_text(
        (DATA / "business_context.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    out = await audit_knowledge_base()
    assert out["status"] == "ok"
    assert out["flagged_article_count"] >= 8
    report = workspace / "drafts" / "kb-audit-report.md"
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    assert "知识库体检报告" in text
    assert "优先处理" in text


def test_unknown_extra_policy_not_flagged() -> None:
    rules = (DATA / "business_context.md").read_text(encoding="utf-8")
    articles = [
        {
            "id": "X1",
            "question": "支持哪些支付方式？",
            "answer": "目前支持微信支付、支付宝、银行卡、花呗和信用卡在线支付。",
            "category": "支付",
        },
        {
            "id": "X2",
            "question": "忘记支付密码怎么办？",
            "answer": "这个我们不管理哦，建议您联系对应的支付平台找回密码。",
            "category": "支付",
        },
    ]
    result = scan_articles(articles, rules)
    assert result["flagged_ids"] == []
