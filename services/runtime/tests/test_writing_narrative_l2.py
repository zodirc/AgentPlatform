from __future__ import annotations

from pathlib import Path

from app.offline.rubric import score_rubric
from app.writing.commitment import (
    COMMIT_MIN_VISIBLE,
    gate_draft_commitment,
    normalize_commitment,
    quota_reject,
)
from app.writing.ledger import HAMMING_MIN, append_ledger, hamming, pond_vector, too_close_to_ledger
from app.writing.narrative.judge import parse_judge_payload, self_agreement
from app.writing.narrative.spec import CORE_FEATURES
from app.writing.narrative.vector import encode_feature_map
from app.writing.subtype import infer_serial_subtype, serial_subtype_block


def test_parse_judge_payload_and_encode() -> None:
    payload = {
        feat.key: (1 if feat.kind == "prevalence" else 3) for feat in CORE_FEATURES
    }
    parsed = parse_judge_payload(__import__("json").dumps(payload))
    assert parsed["affect_embodied"] == 1.0
    vec = encode_feature_map(parsed)
    assert len(vec) == len(CORE_FEATURES)
    assert self_agreement([parsed, parsed]) == 1.0


def test_ledger_hamming_rejects_near_duplicate(tmp_path: Path) -> None:
    vec = pond_vector(
        {
            "start_kind": "self_notice",
            "promise": "power_steps",
            "where": "地铁口",
            "price_axis": "status",
        }
    )
    append_ledger(vec, workspace_root=tmp_path, kind="pond")
    same = pond_vector(
        {
            "start_kind": "self_notice",
            "promise": "power_steps",
            "where": "地铁站",
            "price_axis": "status",
        }
    )
    assert hamming(vec, same) < HAMMING_MIN
    hit = too_close_to_ledger([same], workspace_root=tmp_path)
    assert hit is not None
    assert hit[0] == "ledger_too_close"
    far = pond_vector(
        {
            "start_kind": "granted_path",
            "promise": "costly_truth",
            "where": "山门",
        }
    )
    # Fill comparable slots so Hamming can see distance.
    far["affect_mode"] = "named"
    far["subplot"] = "parallel_theme"
    far["time_order"] = "mid_flashback"
    assert too_close_to_ledger([far], workspace_root=tmp_path) is None


def test_ledger_rejects_same_price_engine_across_start_kinds(tmp_path: Path) -> None:
    burn = pond_vector(
        {
            "start_kind": "granted_path",
            "promise": "power_steps",
            "flavor": "凡人夹层里借火一息，烧寿三年。",
            "opening": "火苗立住，寿数当场少了三年。",
        }
    )
    pay = pond_vector(
        {
            "start_kind": "pulled_in",
            "promise": "costly_truth",
            "flavor": "功簿烙法，修成者偿命。",
            "opening": "簿页自己翻开，名字被烙进去。",
        }
    )
    assert burn["price_class"] == pay["price_class"] == "lifespan"
    assert burn["start_kind"] != pay["start_kind"]
    hit = too_close_to_ledger([burn, pay], workspace_root=tmp_path)
    assert hit is not None and hit[0] == "ledger_too_close"
    mundane = pond_vector(
        {
            "start_kind": "no_extraordinary",
            "promise": "survive_relation",
            "flavor": "车夫还在送米，超凡往后放。",
            "opening": "车辕压过石子，米袋裂开。",
        }
    )
    assert too_close_to_ledger([burn, mundane], workspace_root=tmp_path) is None
    append_ledger(burn, workspace_root=tmp_path, kind="pond")
    later = pond_vector(
        {
            "start_kind": "self_notice",
            "promise": "dread_decode",
            "flavor": "凡人夜里自己发觉能扣寿换火。",
            "opening": "烛火亮了，阳寿少了一截。",
        }
    )
    assert later["price_class"] == "lifespan"
    assert too_close_to_ledger([later, mundane], workspace_root=tmp_path) is not None


def test_pond_vector_prefers_declared_price_axis() -> None:
    from app.writing.ledger import encode_vector

    declared = pond_vector(
        {
            "start_kind": "self_notice",
            "flavor": "凡人夹层里借火一息，烧寿三年。",
            "opening": "寿数当场少了三年。",
            "price_axis": "status",
        }
    )
    assert declared["price_class"] == "status"
    assert encode_vector({"price_class": "body_tax"})["price_class"] == "lifespan"


def test_commitment_quota_and_min_visible(tmp_path: Path) -> None:
    default = normalize_commitment({})
    assert default["affect_mode"] == "embodied"
    err, commit = gate_draft_commitment(
        content="短",
        mode="upsert",
        work_mode="literary",
        section_id="ch1",
        raw=None,
        workspace_root=tmp_path,
    )
    assert err is None and commit is None
    long = "柜门空了。" * (COMMIT_MIN_VISIBLE // 4)
    err, commit = gate_draft_commitment(
        content=long,
        mode="upsert",
        work_mode="literary",
        section_id="ch1",
        raw=None,
        workspace_root=tmp_path,
    )
    assert err is not None and err["error"] == "need_narrative_commitment"
    mixed = normalize_commitment({"affect_mode": "named", "subplot": "parallel_theme"})
    assert quota_reject(mixed, work_mode="literary", workspace_root=tmp_path) is None


def test_fourth_wall_does_not_raise_meta_knowing() -> None:
    wall = score_rubric("却说这城里的规矩不写在告示上。看官且听：诸位都看见了。")
    assert wall["meta_knowing_rate"] == 0.0
    preach = score_rubric("他知道事情不对。心里清楚对方在骗自己。")
    assert preach["meta_knowing_rate"] > 0


def test_serial_subtype_block() -> None:
    assert infer_serial_subtype("写一部凡人流长篇") == "fanren"
    assert "凡人流" in serial_subtype_block("写一部凡人流长篇")
    assert serial_subtype_block("写个日常") == ""
