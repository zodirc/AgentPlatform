from __future__ import annotations

import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from .config import load_suites
from .paths import data_dir, ensure_data_dir, ensure_dirs, suite_data


def _md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(
    url: str,
    dest: Path,
    *,
    label: str = "",
    dataset_i: int = 0,
    dataset_n: int = 0,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"[pull] GET {url}", flush=True)
    last_pct = [-1]
    prefix = f"[pull] {label} " if label else "[pull] "

    def _hook(block_num: int, block_size: int, total: int) -> None:
        if total <= 0:
            if block_num and block_num % 64 == 0:
                mb = (block_num * block_size) / (1024 * 1024)
                print(f"{prefix}… {mb:.1f} MiB downloaded (size unknown)", flush=True)
            return
        pct = int(100 * block_num * block_size / total)
        if pct >= last_pct[0] + 5 or pct >= 100:
            last_pct[0] = pct
            got = min(block_num * block_size, total) / (1024 * 1024)
            tot = total / (1024 * 1024)
            # Structured line for Ops UI parser
            if dataset_n:
                print(
                    f"[progress] pull dataset={dataset_i}/{dataset_n} "
                    f"file={dest.name} pct={min(pct, 100)} "
                    f"size_mib={got:.1f}/{tot:.1f}",
                    flush=True,
                )
            print(
                f"{prefix}… {min(pct, 100)}% ({got:.1f}/{tot:.1f} MiB)",
                flush=True,
            )

    urllib.request.urlretrieve(url, tmp, reporthook=_hook)  # noqa: S310 — pinned official URLs
    tmp.replace(dest)
    print(f"[pull] saved {dest.name} ({dest.stat().st_size / (1024 * 1024):.1f} MiB)", flush=True)


def _beir_dataset_ready(target: Path) -> bool:
    """True when extracted BEIR files look complete (marker optional — heal old caches)."""
    if not target.is_dir():
        return False
    corpus = target / "corpus.jsonl"
    queries = target / "queries.jsonl"
    qrels = target / "qrels" / "test.tsv"
    # Some BEIR layouts nest under <name>/<name>/
    if not corpus.is_file():
        nested = target / target.name
        corpus = nested / "corpus.jsonl"
        queries = nested / "queries.jsonl"
        qrels = nested / "qrels" / "test.tsv"
    return corpus.is_file() and queries.is_file() and qrels.is_file()


def _heal_marker(target: Path, *, name: str, url: str, md5: str) -> None:
    marker = target / ".pulled.json"
    if marker.is_file():
        return
    marker.write_text(
        json.dumps({"name": name, "url": url, "md5": md5, "healed": True}, indent=2),
        encoding="utf-8",
    )


def pull_beir(cfg: dict[str, Any] | None = None, *, force: bool = False) -> Path:
    ensure_data_dir()
    suites = cfg or load_suites()
    retrieval = suites["suites"]["retrieval"]
    root = suite_data("beir")
    root.mkdir(parents=True, exist_ok=True)
    print(f"[pull] BENCH_DATA_DIR={data_dir()}", flush=True)
    meta: dict[str, Any] = {"datasets": []}
    datasets = list(retrieval["datasets"])
    n = len(datasets)

    need: list[dict[str, Any]] = []
    cached_names: list[str] = []
    for ds in datasets:
        name = ds["name"]
        target = root / name
        if not force and _beir_dataset_ready(target):
            _heal_marker(target, name=name, url=ds["url"], md5=(ds.get("md5") or ""))
            cached_names.append(name)
        else:
            need.append(ds)
    approx = sum(float(d.get("approx_mib") or 0) for d in need)
    print(
        f"[pull] plan BEIR: {n} datasets · "
        f"{len(cached_names)} cached · {len(need)} to download"
        + (f" · ~{approx:.0f} MiB remaining" if need else " · nothing to fetch")
        + (f" · skip: {', '.join(cached_names)}" if cached_names else ""),
        flush=True,
    )
    print(
        f"[progress] pull plan total={n} cached={len(cached_names)} "
        f"need={len(need)} approx_mib={approx:.1f}",
        flush=True,
    )

    for i, ds in enumerate(datasets, start=1):
        name = ds["name"]
        target = root / name
        zip_path = root / f"{name}.zip"
        label = f"dataset {i}/{n} {name}"
        if not force and _beir_dataset_ready(target):
            _heal_marker(target, name=name, url=ds["url"], md5=(ds.get("md5") or ""))
            print(f"[pull] {label}: cached — skip", flush=True)
            print(
                f"[progress] pull dataset={i}/{n} file={name} pct=100 cached=1",
                flush=True,
            )
            meta["datasets"].append({"name": name, "path": str(target), "cached": True})
            continue
        if force and target.exists():
            shutil.rmtree(target)
        # Drop incomplete downloads so we do not resume into a bad zip.
        part = zip_path.with_suffix(zip_path.suffix + ".part")
        if part.exists():
            part.unlink()
        approx_one = float(ds.get("approx_mib") or 0)
        print(
            f"[pull] {label}: downloading"
            + (f" (~{approx_one:.1f} MiB)" if approx_one else "")
            + "…",
            flush=True,
        )
        _download(
            ds["url"],
            zip_path,
            label=label,
            dataset_i=i,
            dataset_n=n,
        )
        expect = (ds.get("md5") or "").lower()
        if expect:
            got = _md5_file(zip_path)
            if got != expect:
                raise RuntimeError(f"md5 mismatch for {name}: {got} != {expect}")
        print(f"[pull] {label}: unzip {zip_path.name}", flush=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(root)
        # BEIR zips extract to <name>/
        if not target.exists():
            raise RuntimeError(f"expected extracted dir missing: {target}")
        if not _beir_dataset_ready(target):
            raise RuntimeError(f"BEIR extract incomplete for {name} under {target}")
        _heal_marker(target, name=name, url=ds["url"], md5=expect)
        print(
            f"[progress] pull dataset={i}/{n} file={name} pct=100 cached=0",
            flush=True,
        )
        meta["datasets"].append({"name": name, "path": str(target), "cached": False})

    (root / "pull_manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[pull] BEIR ready under {root}", flush=True)
    return root


def pull_longbench(cfg: dict[str, Any] | None = None, *, force: bool = False) -> Path:
    ensure_data_dir()
    suites = cfg or load_suites()
    ctx = suites["suites"]["context"]
    root = suite_data("longbench")
    root.mkdir(parents=True, exist_ok=True)
    out_file = root / "small_slice.jsonl"
    marker = root / ".pulled.json"
    if out_file.exists() and marker.exists() and not force:
        print(f"[pull] longbench: cached → {out_file}", flush=True)
        print("[progress] pull dataset=1/1 file=longbench pct=100 cached=1", flush=True)
        return root

    try:
        from datasets import load_dataset
    except ImportError as e:
        raise SystemExit(
            "LongBench pull needs `datasets`. "
            "pip install -r eval/official/requirements.txt"
        ) from e

    max_n = int(ctx.get("max_samples_per_task") or 40)
    tasks = list(ctx["tasks"])
    print(
        f"[pull] plan LongBench: {len(tasks)} tasks · ≤{max_n} samples each "
        f"· HF {ctx['hf_dataset']}",
        flush=True,
    )
    rows: list[dict[str, Any]] = []
    for ti, task in enumerate(tasks, start=1):
        print(f"[pull] dataset {ti}/{len(tasks)} {task}", flush=True)
        print(
            f"[progress] pull dataset={ti}/{len(tasks)} file={task} pct=0",
            flush=True,
        )
        ds = load_dataset(
            ctx["hf_dataset"],
            task,
            split="test",
            revision=ctx.get("hf_revision") or "main",
        )
        for i, row in enumerate(ds):
            if i >= max_n:
                break
            rows.append(
                {
                    "task": task,
                    "idx": i,
                    "input": row.get("input") or row.get("context") or "",
                    "context": row.get("context") or "",
                    "question": row.get("input") or row.get("question") or "",
                    "answers": row.get("answers")
                    if row.get("answers") is not None
                    else row.get("answer"),
                    "length": row.get("length"),
                    "dataset": row.get("dataset") or task,
                    "language": row.get("language") or "en",
                    "all_classes": row.get("all_classes"),
                    "_raw_keys": sorted(list(row.keys())),
                }
            )
        print(
            f"[progress] pull dataset={ti}/{len(tasks)} file={task} pct=100",
            flush=True,
        )

    with out_file.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    marker.write_text(
        json.dumps(
            {
                "hf_dataset": ctx["hf_dataset"],
                "tasks": ctx["tasks"],
                "max_samples_per_task": max_n,
                "n_rows": len(rows),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[pull] longbench wrote {len(rows)} rows → {out_file}")
    return root


def pull_swebench(cfg: dict[str, Any] | None = None, *, force: bool = False) -> Path:
    ensure_data_dir()
    suites = cfg or load_suites()
    coding = suites["suites"]["coding"]
    root = suite_data("swebench_lite")
    root.mkdir(parents=True, exist_ok=True)
    out_file = root / "instances.jsonl"
    marker = root / ".pulled.json"
    if out_file.exists() and marker.exists() and not force:
        print(f"[pull] swebench_lite: cached → {out_file}")
        return root

    try:
        from datasets import load_dataset
    except ImportError as e:
        raise SystemExit(
            "SWE-bench pull needs `datasets`. "
            "pip install -r eval/official/requirements.txt"
        ) from e

    print(f"[pull] {coding['hf_dataset']} split={coding.get('split', 'test')}")
    ds = load_dataset(
        coding["hf_dataset"],
        split=coding.get("split") or "test",
        revision=coding.get("hf_revision") or "main",
    )
    max_n = int(coding.get("max_instances") or 0)
    n = 0
    with out_file.open("w", encoding="utf-8") as f:
        for row in ds:
            f.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
            n += 1
            if max_n and n >= max_n:
                break
    marker.write_text(
        json.dumps(
            {
                "hf_dataset": coding["hf_dataset"],
                "split": coding.get("split"),
                "n_instances": n,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[pull] swebench_lite wrote {n} instances → {out_file}")
    return root


def pull_all(*, force: bool = False) -> dict[str, str]:
    ensure_dirs()
    ensure_data_dir()
    cfg = load_suites()
    beir = pull_beir(cfg, force=force)
    lb = pull_longbench(cfg, force=force)
    swe = pull_swebench(cfg, force=force)
    return {"beir": str(beir), "longbench": str(lb), "swebench_lite": str(swe)}
