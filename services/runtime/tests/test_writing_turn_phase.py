from __future__ import annotations

from pathlib import Path

from app.writing.book_scope import explicit_book_scope, infer_book_scope
from app.writing.focus import infer_focus_section_id
from app.writing.outline_phase import resolve_outline_phase, wants_opening_candidates
from app.writing.turn_phase import (
    OUTLINE_AWAIT_HINT,
    continue_kind,
    draft_need_chapter_job_error,
    draft_need_outline_error,
    has_chapter_jobs,
    picking,
    should_await_outline_direction,
    should_gate_outline_wait,
    snapshot,
    write_intent,
)


def test_scope_一部_and_一篇_and_browse() -> None:
    assert explicit_book_scope("写一部小说") == "long"
    assert infer_book_scope("写一部小说") == "long"
    assert infer_book_scope("写一篇都市故事") == "single"
    assert explicit_book_scope("写一篇都市修真，我看看") == "long"
    assert explicit_book_scope("写一篇短篇，我看看") == "short"
    assert wants_opening_candidates("写一篇都市故事") is False
    assert wants_opening_candidates("写一篇都市修真，我看看") is True
    assert wants_opening_candidates("写一篇短篇，我看看") is False
    assert wants_opening_candidates("写一部小说") is True


def test_pick_token_is_not_write_intent() -> None:
    assert write_intent("采用此开篇「废脉剑声」") is False
    assert write_intent("采用此开篇「废脉剑声」。写第一章") is True
    assert write_intent("好", has_chapter_jobs_flag=True, has_manuscript_flag=False) is True
    assert write_intent("好", has_chapter_jobs_flag=False, has_manuscript_flag=False) is False


def test_seeded_book_is_not_chapter_jobs() -> None:
    md = "## 这本书\n\n《废脉剑声》。边荒少年。\n\n简介：剑冢夜里响。\n"
    assert has_chapter_jobs(md) is False
    jobs = (
        "## 这本书\n\n《废脉剑声》。\n\n"
        "## 第一章\n井底试药，把简介里这场写完，不要另起一场。\n"
    )
    assert has_chapter_jobs(jobs) is True


def test_outline_wait_on_pick_without_jobs(tmp_path: Path, monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    (tmp_path / "outline.md").write_text(
        "## 这本书\n\n《废脉剑声》。边荒少年。\n",
        encoding="utf-8",
    )
    snap = snapshot("采用此开篇「废脉剑声」", workspace_root=tmp_path)
    assert snap["picking"] is False
    assert snap["outline_wait"] is True
    assert snap["write_intent"] is False
    assert should_gate_outline_wait("采用此开篇「废脉剑声」", workspace_root=tmp_path) is True
    phase = resolve_outline_phase(
        "采用此开篇「废脉剑声」",
        outline=(tmp_path / "outline.md").read_text(encoding="utf-8"),
        workspace_root=tmp_path,
    )
    assert phase["outline_phase"] == "open"
    assert phase["outline_phase"] != "continue"
    err = draft_need_outline_error("采用此开篇「废脉剑声」", workspace_root=tmp_path)
    assert err and err["error"] == "need_outline"


def test_same_turn_write_intent_still_need_outline(tmp_path: Path, monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    (tmp_path / "outline.md").write_text(
        "## 这本书\n\n《废脉剑声》。\n", encoding="utf-8"
    )
    snap = snapshot("采用此开篇「废脉剑声」。写第一章", workspace_root=tmp_path)
    assert snap["write_intent"] is True
    assert snap["outline_wait"] is True
    assert (
        should_gate_outline_wait(
            "采用此开篇「废脉剑声」。写第一章", workspace_root=tmp_path
        )
        is False
    )
    err = draft_need_outline_error(
        "采用此开篇「废脉剑声」。写第一章", workspace_root=tmp_path
    )
    assert err and err["error"] == "need_outline"
    jobs = (
        "## 这本书\n\n《废脉剑声》。\n\n"
        "## 第一章\n井底试药，把简介里这场写完，不要另起一场。\n"
    )
    assert (
        should_await_outline_direction(
            "采用此开篇「废脉剑声」。写第一章",
            outline=jobs,
            workspace_root=tmp_path,
        )
        is False
    )
    assert (
        should_await_outline_direction(
            "采用此开篇「废脉剑声」",
            outline=jobs,
            workspace_root=tmp_path,
        )
        is True
    )
    assert OUTLINE_AWAIT_HINT.startswith("纲已写入")


def test_next_chapter_not_append() -> None:
    available = ["ch1"]
    assert infer_focus_section_id("下一章", available) == "ch2"
    assert infer_focus_section_id("把这章写完", available) == "ch1"
    assert infer_focus_section_id("接着写", available) == "ch1"
    kind = continue_kind(
        "下一章",
        has_manuscript_flag=True,
        section_ids=available,
    )
    assert kind == "new_chapter"


def test_bare_continue_uses_next_outline_job() -> None:
    outline = (
        "# 第一章\n井底试药，把简介里这场写完。\n\n"
        "# 第二章\n上井之后看见别人的井，少年要把这场写满到能站住。井口的风还没停，灯油只够再点一小会儿，他不打算回头，旧伤也还没让他停下，桶绳还是湿的，井壁上还留着他上次的手印。\n"
    )
    available = ["ch1"]
    assert (
        continue_kind(
            "接着写",
            has_manuscript_flag=True,
            outline=outline,
            section_ids=available,
        )
        == "new_chapter"
    )
    assert infer_focus_section_id("接着写", available, outline=outline) == "ch2"


_FAT_JOB = (
    "井底少年要把今晚这场试药写完。旧伤让他不敢下第二趟。"
    "药还在石缝里，他已经咽过一次，第二次要自己决定伸不伸手。"
    "井沿上的人还在等他上来，灯油只够再点一小会儿，桶绳还是湿的。"
)


def test_next_chapter_needs_a_near_job(tmp_path: Path, monkeypatch) -> None:
    from app.settings import settings
    from app.writing.manuscript import upsert_section

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "manuscript.md").write_text(
        upsert_section("", "ch1", "井底已经写过一场。"),
        encoding="utf-8",
    )
    thin = "## 这本书\n《废脉剑声》。\n\n## 第一章\n井底试药。\n\n## 第二章\n上井看看。\n"
    (tmp_path / "outline.md").write_text(thin, encoding="utf-8")
    err = draft_need_chapter_job_error("下一章", workspace_root=tmp_path)
    assert err and err["error"] == "need_chapter_job"
    assert err["section_id"] == "ch2"
    assert (
        continue_kind(
            "接着写",
            has_manuscript_flag=True,
            outline=thin,
            section_ids=["ch1"],
        )
        == "append_this"
    )
    fat = (
        "## 这本书\n《废脉剑声》。人怎么变：从怕井到肯再下一次。\n\n"
        f"## 第二章\n{_FAT_JOB}\n"
    )
    (tmp_path / "outline.md").write_text(fat, encoding="utf-8")
    assert draft_need_chapter_job_error("下一章", workspace_root=tmp_path) is None
    assert draft_need_chapter_job_error("写第二章", workspace_root=tmp_path) is None


def test_first_chapter_thin_job_is_not_enough(tmp_path: Path, monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    (tmp_path / "outline.md").write_text(
        "## 这本书\n《废脉剑声》。\n\n## 第一章\n井底试药，把这场写完。\n",
        encoding="utf-8",
    )
    err = draft_need_chapter_job_error("写第一章", workspace_root=tmp_path)
    assert err and err["error"] == "need_chapter_job"
    assert err["section_id"] == "ch1"
    (tmp_path / "outline.md").write_text(
        f"## 这本书\n《废脉剑声》。\n\n## 主线一句话\n人怎么变，从怕井到肯再下去。\n\n"
        f"## 第一章\n{_FAT_JOB}\n",
        encoding="utf-8",
    )
    assert draft_need_chapter_job_error("写第一章", workspace_root=tmp_path) is None
    assert draft_need_chapter_job_error("写一篇都市故事", workspace_root=tmp_path) is None
    bare = tmp_path / "bare"
    bare.mkdir()
    assert (
        draft_need_chapter_job_error("写一章长篇第二章 作者模式", workspace_root=bare)
        is None
    )


def test_short_skips_picking() -> None:
    assert picking("写一篇短篇小说") is False
    assert picking("写一篇故事") is False
    assert picking("写一章长篇修真，我看看") is True
    assert picking("写第二章") is False
