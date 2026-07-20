from __future__ import annotations

from app.retrieval.path_filter import (
    filter_hits_by_path_prefix,
    normalize_path_prefix,
    path_matches_prefix,
)


def test_normalize_path_prefix_none_and_blank() -> None:
    assert normalize_path_prefix(None) == (None, None)
    assert normalize_path_prefix("") == (None, None)
    assert normalize_path_prefix("  ") == (None, None)


def test_normalize_path_prefix_auto_sources() -> None:
    assert normalize_path_prefix("hr") == ("sources/hr", None)
    assert normalize_path_prefix("sources/hr") == ("sources/hr", None)
    assert normalize_path_prefix("sources/hr/") == ("sources/hr", None)
    assert normalize_path_prefix("legal/nda") == ("sources/legal/nda", None)


def test_normalize_path_prefix_rejects_escape() -> None:
    assert normalize_path_prefix("../etc")[0] is None
    assert ".." in (normalize_path_prefix("../etc")[1] or "")
    assert normalize_path_prefix("/etc/passwd")[0] is None


def test_path_matches_prefix() -> None:
    assert path_matches_prefix("sources/hr/leave-policy.md", "sources/hr")
    assert path_matches_prefix("sources/hr", "sources/hr")
    assert not path_matches_prefix("sources/legal/nda.md", "sources/hr")
    assert not path_matches_prefix("sources/hrx/x.md", "sources/hr")


def test_filter_hits_by_path_prefix() -> None:
    hits = [
        {"path": "sources/hr/a.md", "excerpt": "e"},
        {"path": "sources/legal/b.md", "excerpt": "e"},
    ]
    filtered, meta = filter_hits_by_path_prefix(hits, path_prefix="hr")
    assert len(filtered) == 1
    assert filtered[0]["path"] == "sources/hr/a.md"
    assert meta["filters"]["applied"] is True

    empty, err_meta = filter_hits_by_path_prefix(hits, path_prefix="../x")
    assert empty == []
    assert err_meta["filters"]["applied"] is False
