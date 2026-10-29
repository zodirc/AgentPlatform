"""本地接头的台账、回收、撤销和导入。断言的是失败条件和零删除。"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

from app.writing_host.errors import SnapshotCorrupt, StorageLow, TurnNotRevertable
from app.writing_host.protocol import (
    ModelConfig,
    TurnBudget,
    export_work,
    gc_work,
    import_work,
    list_resumable,
    list_turn_history,
    revert_turn,
    start_turn,
)
from app.writing_host.schema import EVENT_KEEP_TURNS
from app.writing_host.storage import (
    Crash,
    begin_turn,
    finish_turn,
    import_staging_root,
    open_work,
    work_lock,
)
from app.writing_host.works import snapshot_turn

_crash = None


def setup_function() -> None:
    global _crash
    import app.writing_host.storage as storage

    _crash = storage
    storage.crash_at = None


def _record(work: Path, turn_id: str, text: str, *, state: str = "completed") -> None:
    work.mkdir(parents=True, exist_ok=True)
    with work_lock(work):
        begin_turn(work, turn_id)
        (work / "outline.md").write_text(text, encoding="utf-8")
        snapshot_turn(work, turn_id)
        if state != "running":
            finish_turn(work, turn_id, state, budget_ms=0)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_revert_follows_ledger_seq_not_turn_id(tmp_path: Path) -> None:
    work = tmp_path / "book"
    ids = [str(uuid4()) for _ in range(5)]
    for index, turn_id in enumerate(ids):
        _record(work, turn_id, f"v{index}\n")
    revert_turn(work, ids[2])
    history = list_turn_history(work)
    assert [row.turn_id for row in history] == ids[:2]
    assert [row.seq for row in history] == [1, 2]
    assert (work / "outline.md").read_text(encoding="utf-8") == "v2\n"
    assert not (work / ".agent" / "snapshots" / "turns" / f"{ids[2]}.json").exists()


def test_partial_object_never_takes_the_hash_name(tmp_path: Path) -> None:
    work = tmp_path / "book"
    turn_id = str(uuid4())
    work.mkdir()
    with work_lock(work):
        begin_turn(work, turn_id)
        (work / "outline.md").write_text("正文\n", encoding="utf-8")
        _crash.crash_at = "before-object-rename"
        with pytest.raises(Crash):
            snapshot_turn(work, turn_id)
        _crash.crash_at = None
    digest = _sha("正文\n".encode())
    objects = work / ".agent" / "snapshots" / "objects"
    assert not (objects / digest).exists()
    assert any(path.name.startswith("tmp-") for path in objects.iterdir())


def test_corrupt_object_is_not_written_back(tmp_path: Path) -> None:
    work = tmp_path / "book"
    turn_id = str(uuid4())
    _record(work, turn_id, "原文\n")
    objects = work / ".agent" / "snapshots" / "objects"
    target = next(objects.iterdir())
    target.write_bytes(b"tampered")
    (work / "outline.md").write_text("改过\n", encoding="utf-8")
    with pytest.raises(SnapshotCorrupt):
        revert_turn(work, turn_id)
    assert (work / "outline.md").read_text(encoding="utf-8") == "改过\n"


def test_existing_bad_object_is_overwritten(tmp_path: Path) -> None:
    work = tmp_path / "book"
    data = "同样的稿\n".encode()
    digest = _sha(data)
    objects = work / ".agent" / "snapshots" / "objects"
    objects.mkdir(parents=True)
    (objects / digest).write_bytes(b"x" * len(data))
    _record(work, str(uuid4()), data.decode())
    assert (objects / digest).read_bytes() == data


def test_crash_between_snapshot_steps_reconciles(tmp_path: Path) -> None:
    work = tmp_path / "book"
    turn_id = str(uuid4())
    points = (
        "before-object-rename",
        "after-objects-before-manifest",
        "before-ledger-rename",
    )
    for point in points:
        book = work / point
        book.mkdir(parents=True)
        with work_lock(book):
            begin_turn(book, turn_id)
            (book / "outline.md").write_text("稿\n", encoding="utf-8")
            _crash.crash_at = point
            with pytest.raises(Crash):
                snapshot_turn(book, turn_id)
            _crash.crash_at = None
        opened = open_work(book)
        row = opened["turns"][0]
        assert row["turn_id"] == turn_id
        assert row["state"] in {"interrupted", "failed"}
        assert row["state"] == "failed"
        if point == "before-ledger-rename":
            assert row["snapshot"] is True
            assert (book / ".agent" / "snapshots" / "turns" / f"{turn_id}.json").is_file()
        else:
            assert not row.get("snapshot")
        report = gc_work(book)
        assert report.aborted == ""
        again = open_work(book)
        assert any(item["turn_id"] == turn_id for item in again["turns"])


def test_high_schema_manifest_deletes_nothing(tmp_path: Path) -> None:
    work = tmp_path / "book"
    turn_id = "kept"
    _record(work, turn_id, "留着\n")
    manifest = work / ".agent" / "snapshots" / "turns" / f"{turn_id}.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["schema_version"] = 99
    manifest.write_text(json.dumps(data), encoding="utf-8")
    orphan = work / ".agent" / "snapshots" / "objects" / ("ab" * 32)
    orphan.write_bytes(b"orphan")
    report = gc_work(work)
    assert report.aborted == "manifest_schema"
    assert report.deleted == 0
    assert orphan.is_file()
    assert manifest.is_file()


def test_corrupt_manifest_and_ledger_delete_nothing(tmp_path: Path) -> None:
    work = tmp_path / "book"
    _record(work, "t", "稿\n")
    orphan = work / ".agent" / "snapshots" / "objects" / ("cd" * 32)
    orphan.write_bytes(b"orphan")
    manifest = next((work / ".agent" / "snapshots" / "turns").glob("*.json"))
    manifest.write_text("{", encoding="utf-8")
    report = gc_work(work)
    assert report.aborted == "manifest_corrupt"
    assert report.deleted == 0
    assert orphan.is_file()

    other = tmp_path / "ledger"
    _record(other, "t", "稿\n")
    kept = next((other / ".agent" / "snapshots" / "objects").iterdir())
    (other / ".agent" / "turns.json").write_text("{", encoding="utf-8")
    report = gc_work(other)
    assert report.aborted == "ledger_corrupt"
    assert report.deleted == 0
    assert kept.is_file()
    assert (other / ".agent" / "turns.json").read_text(encoding="utf-8") == "{"


def test_orphan_referenced_again_is_kept(tmp_path: Path) -> None:
    work = tmp_path / "book"
    data = "复活\n".encode()
    digest = _sha(data)
    objects = work / ".agent" / "snapshots" / "objects"
    objects.mkdir(parents=True)
    (objects / digest).write_bytes(data)
    first = gc_work(work, budget_ms=0)
    assert first.deleted == 0
    assert first.candidates >= 1
    _record(work, "again", data.decode())
    second = gc_work(work)
    assert (objects / digest).is_file()
    assert all(path.name != digest or path.is_file() for path in objects.iterdir())
    assert second.aborted == ""


def test_turn_outside_window_is_not_revertable_and_interrupted_stays(tmp_path: Path) -> None:
    work = tmp_path / "book"
    ids = [f"turn-{index:02d}" for index in range(EVENT_KEEP_TURNS + 1)]
    for index, turn_id in enumerate(ids):
        _record(work, turn_id, f"v{index}\n")
    with pytest.raises(TurnNotRevertable):
        revert_turn(work, ids[0])
    assert (work / "outline.md").read_text(encoding="utf-8") == f"v{EVENT_KEEP_TURNS}\n"

    held = tmp_path / "held"
    first = "turn-held"
    held.mkdir()
    with work_lock(held):
        begin_turn(held, first)
        (held / "outline.md").write_text("最初\n", encoding="utf-8")
        snapshot_turn(held, first)
        checkpoint = held / ".agent" / "checkpoints" / f"{first}.json"
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(json.dumps({"schema_version": 1, "step_index": 3, "state": {}}), encoding="utf-8")
        for index in range(EVENT_KEEP_TURNS):
            begin_turn(held, f"later-{index}")
            (held / "outline.md").write_text(f"later-{index}\n", encoding="utf-8")
            snapshot_turn(held, f"later-{index}")
            finish_turn(held, f"later-{index}", "completed", budget_ms=0)
    opened = open_work(held)
    assert opened["turns"][0]["state"] == "interrupted"
    report = gc_work(held)
    assert report.aborted == ""
    assert any(row.turn_id == first for row in list_turn_history(held))
    assert [row.turn_id for row in list_resumable(held)] == [first]
    revert_turn(held, first)
    assert (held / "outline.md").read_text(encoding="utf-8") == "最初\n"


def test_gc_stops_at_budget_and_does_not_double_count(tmp_path: Path) -> None:
    work = tmp_path / "book"
    ids = [f"old-{index}" for index in range(3)]
    for index, turn_id in enumerate(ids):
        _record(work, turn_id, f"v{index}\n")
    for index in range(EVENT_KEEP_TURNS):
        _record(work, f"keep-{index}", f"keep-{index}\n")
    paused = gc_work(work, budget_ms=0)
    assert paused.deleted == 0
    assert paused.candidates > 0
    assert (work / ".agent" / "snapshots" / "turns" / f"{ids[0]}.json").is_file()
    _crash.crash_at = "after-first-delete"
    with pytest.raises(Crash):
        gc_work(work)
    _crash.crash_at = None
    resumed = gc_work(work)
    assert resumed.deleted == paused.candidates - 1
    assert not (work / ".agent" / "snapshots" / "turns" / f"{ids[0]}.json").exists()
    again = gc_work(work)
    assert again.deleted == 0


def test_import_rejects_bad_archives_without_leaving_a_work(tmp_path: Path) -> None:
    cases = {
        "hash": {"export.json": _export_meta(), ".agent/snapshots/objects/" + ("ab" * 32): b"nope"},
        "escape": {"export.json": _export_meta(), "../escape.txt": b"out"},
        "link": None,
    }
    for name, members in cases.items():
        archive = tmp_path / f"{name}.zip"
        dest = tmp_path / f"dest-{name}"
        _write_zip(archive, members, link=name == "link")
        with pytest.raises(Exception):
            import_work(archive, dest)
        assert not dest.exists()
        staging = import_staging_root(dest)
        assert not staging.exists() or not any(staging.iterdir())

    existing = tmp_path / "already"
    existing.mkdir()
    (existing / "outline.md").write_text("不动\n", encoding="utf-8")
    archive = tmp_path / "exists.zip"
    _write_zip(archive, {"export.json": _export_meta(), "outline.md": "新\n"})
    with pytest.raises(FileExistsError):
        import_work(archive, existing)
    assert (existing / "outline.md").read_text(encoding="utf-8") == "不动\n"
    staging = import_staging_root(existing)
    assert not staging.exists() or not any(staging.iterdir())


def test_export_manuscript_skips_history_and_full_roundtrips(tmp_path: Path) -> None:
    work = tmp_path / "book"
    _record(work, "t1", "稿\n")
    plain = tmp_path / "plain.zip"
    export_work(work, plain)
    with zipfile.ZipFile(plain) as archive:
        names = set(archive.namelist())
    assert "outline.md" in names
    assert not any(name.startswith(".agent/snapshots/") for name in names)
    full = tmp_path / "full.zip"
    export_work(work, full, mode="full")
    imported = import_work(full, tmp_path / "restored")
    assert any(item.doc_id == "outline" for item in imported.documents)
    assert [row.turn_id for row in list_turn_history(tmp_path / "restored")] == ["t1"]


@pytest.mark.asyncio
async def test_low_space_does_not_start_a_turn(tmp_path: Path) -> None:
    work = tmp_path / "book"
    model = ModelConfig(base_url="http://127.0.0.1", api_key="x", model="m")
    with pytest.raises(StorageLow):
        await start_turn(
            work_root=work,
            message="写一段",
            model=model,
            budget=TurnBudget(max_steps=1),
            min_free_bytes=1 << 60,
        )
    assert not (work / ".agent" / "turns.json").exists() or json.loads(
        (work / ".agent" / "turns.json").read_text(encoding="utf-8")
    )["turns"] == []


def _export_meta() -> str:
    return json.dumps({"schema_versions": {"ledger": 1, "snapshot": 1}})


def _write_zip(path: Path, members: dict[str, str | bytes] | None, *, link: bool = False) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        if link:
            archive.writestr("export.json", _export_meta())
            info = zipfile.ZipInfo("link")
            info.external_attr = (0o120777) << 16
            archive.writestr(info, "outline.md")
            return
        assert members is not None
        for name, payload in members.items():
            data = payload.encode() if isinstance(payload, str) else payload
            archive.writestr(name, data)


def test_cli_gc_prints_only_json_and_zero_deletes_on_a_corrupt_ledger(tmp_path: Path, capsys) -> None:
    from app.writing_host.cli import main

    work = tmp_path / "book"
    (work / ".agent").mkdir(parents=True)
    (work / ".agent" / "turns.json").write_text("{", encoding="utf-8")
    assert main(["--work", str(work), "--gc"]) == 0
    line = capsys.readouterr().out.strip()
    payload = json.loads(line)
    assert list(payload) == [
        "gc_marked",
        "gc_candidates",
        "gc_deleted",
        "gc_aborted",
        "gc_bytes_reclaimed",
    ]
    assert payload["gc_deleted"] == 0
    assert payload["gc_bytes_reclaimed"] == 0
    assert payload["gc_aborted"] == "ledger_corrupt"
