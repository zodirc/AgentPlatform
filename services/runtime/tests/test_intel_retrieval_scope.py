"""Scenario retrieval scope + intel exact lookup (no index sync)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.retrieval.scenario_scope import (
    filter_hits_by_excludes,
    policy_from_mapping,
    resolve_search_path_prefix,
)
from app.scenarios.registry import ScenarioProfile, ScenarioRegistry
from app.tools.core import intel_enrich


def test_policy_from_mapping_defaults() -> None:
    p = policy_from_mapping(
        {
            "default_path_prefix": "seed/intel",
            "exclude_path_prefixes": ["seed/intel", ""],
        }
    )
    assert p.default_path_prefix == "seed/intel"
    assert p.exclude_path_prefixes == ("seed/intel",)


def test_resolve_search_path_prefix_applies_intel_default(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = ScenarioProfile(
        scenario_id="intel",
        display_name="intel",
        system_prompt="",
        tool_names=["search_sources"],
        retrieval={"default_path_prefix": "seed/intel"},
    )
    ScenarioRegistry.register(profile)
    effective, meta = resolve_search_path_prefix(None, scenario_id="intel")
    assert effective == "seed/intel"
    assert meta["applied_default"] is True
    # Explicit override wins
    effective2, meta2 = resolve_search_path_prefix("sources/alerts", scenario_id="intel")
    assert effective2 == "sources/alerts"
    assert meta2["applied_default"] is False


def test_writing_excludes_intel_hits() -> None:
    profile = ScenarioProfile(
        scenario_id="writing",
        display_name="writing",
        system_prompt="",
        tool_names=["search_sources"],
        retrieval={"exclude_path_prefixes": ["seed/intel"]},
    )
    ScenarioRegistry.register(profile)
    hits = [
        {"path": "sources/seed/writing/dramas/a.md", "excerpt": "ok"},
        {"path": "sources/seed/intel/vendor/actors/x.md", "excerpt": "bad"},
    ]
    filtered, meta = filter_hits_by_excludes(hits, scenario_id="writing")
    assert len(filtered) == 1
    assert filtered[0]["path"].endswith("a.md")
    assert meta["removed"] == 1


@pytest.mark.asyncio
async def test_lookup_indicator_reads_seed_ioc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_ioc = tmp_path / "sources" / "seed" / "intel" / "ioc"
    seed_ioc.mkdir(parents=True)
    card = {
        "indicator": "203.0.113.10",
        "normalized": "203.0.113.10",
        "type": "ip",
        "reputation_stub": "suspicious",
        "tags": ["demo"],
        "related": [],
        "sources": ["test"],
        "raw_ref": "sources/seed/intel/ioc/203.0.113.10.json",
        "summary": "test scanner",
    }
    (seed_ioc / "203.0.113.10.json").write_text(json.dumps(card), encoding="utf-8")
    note = tmp_path / "sources" / "seed" / "intel" / "_demo" / "lab-notes"
    note.mkdir(parents=True)
    (note / "scanner-203.md").write_text(
        "# note\n\nMentions 203.0.113.10 as scanner.\n", encoding="utf-8"
    )
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    # Avoid fixture paths from the real checkout dominating
    monkeypatch.setattr(intel_enrich, "_ioc_dirs", lambda: [seed_ioc])
    monkeypatch.setattr(
        intel_enrich,
        "_intel_corpus_roots",
        lambda: [tmp_path / "sources" / "seed" / "intel"],
    )

    enrich = await intel_enrich.enrich_ioc("203.0.113.10")
    assert enrich["status"] == "ok"

    looked = await intel_enrich.lookup_indicator("203.0.113.10", limit=5)
    assert looked["status"] == "ok"
    assert looked["retrieval"] == "exact-local"
    assert any(h.get("kind") == "ioc_card" for h in looked["hits"])
    assert any("203.0.113.10" in str(h.get("excerpt", "")) or "scanner" in str(h.get("path", "")) for h in looked["hits"])


def test_intel_profile_yaml_loads_retrieval() -> None:
    ScenarioRegistry.load()
    intel = ScenarioRegistry.get("intel")
    assert intel.retrieval.get("default_path_prefix") == "seed/intel"
    writing = ScenarioRegistry.get("writing")
    assert "seed/intel" in (writing.retrieval.get("exclude_path_prefixes") or [])
