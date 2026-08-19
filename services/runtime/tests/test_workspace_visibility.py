from app.workspace_visibility import apply_seed_listing, filter_work_surface_list_entries


def test_filter_hides_harness_and_pending_cards() -> None:
    assert filter_work_surface_list_entries(".", [".agent/", "sources/", "drafts/"]) == [
        "sources/",
        "drafts/",
    ]
    assert filter_work_surface_list_entries("sources/cards", ["pending/", "ok.md"]) == [
        "ok.md"
    ]


def test_apply_seed_listing_injects_when_isolated_symlink_looks_like_file() -> None:
    out = apply_seed_listing(
        "sources",
        ["mine.md", "seed"],
        seed_visible=True,
        seed_present=True,
    )
    assert out == ["mine.md", "seed/"]


def test_apply_seed_listing_hides_when_visibility_off() -> None:
    out = apply_seed_listing(
        "sources",
        ["mine.md", "seed/"],
        seed_visible=False,
        seed_present=True,
    )
    assert out == ["mine.md"]
