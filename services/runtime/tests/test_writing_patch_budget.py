"""Patch budget, rewrite_window, delivery gate, and span replace."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.engine.state import TurnState
from app.engine.verify_receipt import should_inject_writing_delivery_hold
from app.tools.core import tools as core
from app.writing.delivery_gate import (
    finalize_writing_turn_summary,
    manifest_delivery_blockers,
    manifest_delivery_ready,
)
from app.writing.patch_budget import (
    MAX_PATCHES_PER_PENALTY_KEY,
    check_propose_patch_allowed,
    count_patch_attempts,
    note_prose_patch_applied,
    patch_budget_exhausted,
    record_patch_attempt,
)
from app.writing.span_replace import replace_span_in_manuscript


def test_patch_budget_exhausted_after_three() -> None:
    assert MAX_PATCHES_PER_PENALTY_KEY == 5
    manifest: dict = {"patch_budget": {}}
    sid = "ch1"
    for _ in range(MAX_PATCHES_PER_PENALTY_KEY):
        record_patch_attempt(
            manifest, section_id=sid, penalty_key="staccato_uniform", old_text="「来。」"
        )
    assert count_patch_attempts(
        manifest, section_id=sid, penalty_key="staccato_uniform"
    ) == MAX_PATCHES_PER_PENALTY_KEY
    assert patch_budget_exhausted(
        manifest, section_id=sid, penalty_key="staccato_uniform"
    )


def test_check_propose_patch_blocked_when_budget_exhausted() -> None:
    manifest: dict = {
        "section_drafts": {
            "ch1": {
                "repair_span": {
                    "key": "staccato_uniform",
                    "old_text": "「来。」\n「坐。」",
                }
            }
        },
        "patch_budget": {
            "ch1": {"by_key": {"staccato_uniform": MAX_PATCHES_PER_PENALTY_KEY}}
        },
    }
    prior = manifest["section_drafts"]["ch1"]
    err = check_propose_patch_allowed(
        manifest,
        section_id="ch1",
        old_text="「来。」\n「坐。」",
        prior=prior,
    )
    assert err is not None
    assert err["error"] == "patch_budget_exhausted"
    assert err["rewrite_policy"] == "rewrite_window"


def test_check_propose_patch_repeat_blocked() -> None:
    prior = {
        "repair_span": {
            "key": "staccato_uniform",
            "old_text": "「来。」\n「坐。」\n「走。」",
        }
    }
    manifest = {
        "patch_budget": {
            "ch1": {
                "by_key": {"staccato_uniform": 1},
                "last": [{"key": "staccato_uniform", "old_text": "「来。」\n「坐。」\n「走。」"}],
            }
        }
    }
    err = check_propose_patch_allowed(
        manifest,
        section_id="ch1",
        old_text="「来。」\n「坐。」\n「走。」",
        prior=prior,
    )
    assert err is not None
    assert err["error"] == "patch_repeat_blocked"


def test_check_propose_patch_unnecessary_when_net_ok() -> None:
    prior = {"net_signal": 0.2, "l0_hits": []}
    err = check_propose_patch_allowed(
        {},
        section_id="ch1",
        old_text="任意",
        prior=prior,
    )
    assert err is not None
    assert err["error"] == "patch_unnecessary"


def test_manifest_delivery_blockers() -> None:
    manifest = {
        "section_drafts": {
            "ch1": {"l0_hits": ["staccato_uniform"], "length_short": True},
        }
    }
    blockers = manifest_delivery_blockers(manifest)
    assert any("staccato_uniform" in b for b in blockers)
    assert any("length_short" in b for b in blockers)
    assert not manifest_delivery_ready(manifest)


def test_finalize_writing_turn_summary_replaces_false_completion(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "workspace_root", str(workspace))
    turn_id = uuid4()
    manifest_dir = workspace / ".agent" / "work" / "turns"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / f"{turn_id}.json").write_text(
        '{"section_drafts":{"ch1":{"l0_hits":["staccato_uniform"]}}}',
        encoding="utf-8",
    )
    out = finalize_writing_turn_summary(
        turn_id=turn_id,
        session_id=uuid4(),
        summary="第一章已完成，请过目。",
    )
    assert "交付门" in out
    assert "已完成" not in out or "禁止" in out


def test_finalize_writing_turn_summary_passthrough_without_manifest() -> None:
    raw = "budget exceeded"
    out = finalize_writing_turn_summary(
        turn_id=uuid4(),
        session_id=uuid4(),
        summary=raw,
    )
    assert out == raw


def test_should_inject_writing_delivery_hold() -> None:
    turn_id = uuid4()
    session_id = uuid4()
    state = TurnState(
        turn_id=turn_id,
        session_id=session_id,
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="writing",
        step_count=5,
        max_steps=40,
    )
    assert not should_inject_writing_delivery_hold(state)
    state.scenario_id = "coding"
    assert not should_inject_writing_delivery_hold(state)


def test_replace_span_dedupes_duplicate_lines_in_section() -> None:
    old = "「来。」\n「坐。」"
    doc = f"# ch1\n\n前缀{old}\n中间{old}\n后缀\n"
    out = replace_span_in_manuscript(
        doc,
        section_id="ch1",
        old_text=old,
        new_text="河工把规矩说满。",
    )
    assert out is not None
    assert old not in out
    assert out.count("河工把规矩说满。") == 2


@pytest.mark.asyncio
async def test_propose_patch_budget_exhausted_integration(workspace) -> None:
    turn_id = uuid4()
    path = "drafts/manuscript.md"
    target = workspace / "drafts" / "manuscript.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    old = "旧句。"
    target.write_text(f"# ch1\n\n{old}\n", encoding="utf-8")
    manifest_dir = workspace / ".agent" / "work" / "turns"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{turn_id}.json"
    manifest_path.write_text(
        (
            '{"section_drafts":{"ch1":{"repair_span":{"key":"hinge_dense","old_text":"旧句。"}}},'
            f'"patch_budget":{{"ch1":{{"by_key":{{"hinge_dense":{MAX_PATCHES_PER_PENALTY_KEY}}}}}}}}}'
        ),
        encoding="utf-8",
    )
    blocked = await core.propose_patch(
        path=path,
        old_text=old,
        new_text="新句。",
        turn_id=turn_id,
    )
    assert blocked.get("error") == "patch_budget_exhausted"


@pytest.mark.asyncio
async def test_propose_patch_does_not_count_until_applied(workspace) -> None:
    turn_id = uuid4()
    path = "drafts/manuscript.md"
    target = workspace / "drafts" / "manuscript.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    old = "旧句。"
    target.write_text(f"# ch1\n\n{old}\n", encoding="utf-8")
    manifest_dir = workspace / ".agent" / "work" / "turns"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{turn_id}.json"
    manifest_path.write_text(
        '{"section_drafts":{"ch1":{"repair_span":{"key":"hinge_dense","old_text":"旧句。"}}}}',
        encoding="utf-8",
    )
    result = await core.propose_patch(
        path=path,
        old_text=old,
        new_text="新句。",
        turn_id=turn_id,
    )
    assert result.get("status") == "pending"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert not data.get("patch_budget")


@pytest.mark.asyncio
async def test_apply_patch_records_budget(workspace) -> None:
    turn_id = uuid4()
    path = "drafts/manuscript.md"
    target = workspace / "drafts" / "manuscript.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    old = "旧句。"
    target.write_text(f"# ch1\n\n{old}\n", encoding="utf-8")
    manifest_dir = workspace / ".agent" / "work" / "turns"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{turn_id}.json"
    manifest_path.write_text(
        '{"section_drafts":{"ch1":{"repair_span":{"key":"hinge_dense","old_text":"旧句。"}}}}',
        encoding="utf-8",
    )
    applied = await core.apply_patch(
        path=path,
        old_text=old,
        new_text="新句。",
        turn_id=turn_id,
    )
    assert applied.get("status") == "applied"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert (
        data.get("patch_budget", {})
        .get("ch1", {})
        .get("by_key", {})
        .get("hinge_dense")
        == 1
    )


@pytest.mark.asyncio
async def test_draft_section_rewrite_window(workspace) -> None:
    turn_id = uuid4()
    path = workspace / "drafts" / "manuscript.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    old_span = "「来。」\n「坐。」\n「走。」"
    path.write_text(f"# ch1\n\n前缀{old_span}后缀\n", encoding="utf-8")
    manifest_dir = workspace / ".agent" / "work" / "turns"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / f"{turn_id}.json").write_text(
        json.dumps(
            {
                "section_drafts": {
                    "ch1": {
                        "repair_span": {
                            "key": "staccato_uniform",
                            "old_text": old_span,
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    replacement = "河工在门槛上敲了敲烟袋，把规矩说满，又指了指外头的水线。"
    result = await core.draft_section(
        "ch1",
        replacement,
        turn_id=turn_id,
        mode="rewrite_window",
    )
    assert result.get("status") == "drafted"
    assert result.get("mode") == "rewrite_window"
    text = path.read_text(encoding="utf-8")
    assert old_span not in text
    assert replacement in text


@pytest.mark.asyncio
async def test_draft_section_rewrite_window_with_duplicate_lines(workspace) -> None:
    turn_id = uuid4()
    path = workspace / "drafts" / "manuscript.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    old_span = "重复句。"
    path.write_text(
        f"# ch1\n\n前文{old_span}\n后文{old_span}\n",
        encoding="utf-8",
    )
    manifest_dir = workspace / ".agent" / "work" / "turns"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / f"{turn_id}.json").write_text(
        json.dumps(
            {
                "section_drafts": {
                    "ch1": {
                        "repair_span": {"key": "staccato_uniform", "old_text": old_span}
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    replacement = "河工把渡税说清楚，又指了指外头的水线。"
    result = await core.draft_section(
        "ch1",
        replacement,
        turn_id=turn_id,
        mode="rewrite_window",
    )
    assert result.get("status") == "drafted"
    text = path.read_text(encoding="utf-8")
    assert old_span not in text
    assert text.count(replacement) == 2


@pytest.mark.asyncio
async def test_export_blocked_while_manifest_open(workspace) -> None:
    turn_id = uuid4()
    manifest_dir = workspace / ".agent" / "work" / "turns"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / f"{turn_id}.json").write_text(
        '{"section_drafts":{"ch1":{"l0_hits":["staccato_uniform"]}},"revisions":{"ch1":"drafts/ch1.md"}}',
        encoding="utf-8",
    )
    drafts = workspace / "drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    (drafts / "ch1.md").write_text("正文", encoding="utf-8")
    result = await core.export_document(
        section_ids=["ch1"],
        source="current_draft",
        turn_id=turn_id,
    )
    assert result.get("delivery_status") == "blocked"
