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
from collections.abc import Callable
from contextvars import ContextVar, Token
_pull_log_sink: ContextVar[Callable[[str], None] | None] = ContextVar('official_bench_pull_log_sink', default=None)

def set_pull_log_sink(sink: Callable[[str], None] | None) -> Token:
    return _pull_log_sink.set(sink)

def reset_pull_log_sink(token: Token) -> None:
    _pull_log_sink.reset(token)

def _log(msg: str) -> None:
    print(msg, flush=True)
    sink = _pull_log_sink.get()
    if sink is None:
        return
    try:
        sink(msg)
    except Exception:
        pass

def _md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open('rb') as f:
        for chunk in iter(lambda : f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def _download(url: str, dest: Path, *, label: str='', dataset_i: int=0, dataset_n: int=0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + '.part')
    _log(f'[pull] GET {url}')
    last_pct = [-1]
    prefix = f'[pull] {label} ' if label else '[pull] '

    def _hook(block_num: int, block_size: int, total: int) -> None:
        if total <= 0:
            if block_num and block_num % 64 == 0:
                mb = block_num * block_size / (1024 * 1024)
                _log(f'{prefix}… {mb:.1f} MiB downloaded (size unknown)')
            return
        pct = int(100 * block_num * block_size / total)
        if pct >= last_pct[0] + 5 or pct >= 100:
            last_pct[0] = pct
            got = min(block_num * block_size, total) / (1024 * 1024)
            tot = total / (1024 * 1024)
            if dataset_n:
                _log(f'[progress] pull dataset={dataset_i}/{dataset_n} file={dest.name} pct={min(pct, 100)} size_mib={got:.1f}/{tot:.1f}')
            _log(f'{prefix}… {min(pct, 100)}% ({got:.1f}/{tot:.1f} MiB)')
    urllib.request.urlretrieve(url, tmp, reporthook=_hook)
    tmp.replace(dest)
    _log(f'[pull] saved {dest.name} ({dest.stat().st_size / (1024 * 1024):.1f} MiB)')

def _beir_dataset_ready(target: Path) -> bool:
    """True when extracted BEIR files look complete (marker optional — heal old caches)."""
    if not target.is_dir():
        return False
    corpus = target / 'corpus.jsonl'
    queries = target / 'queries.jsonl'
    qrels = target / 'qrels' / 'test.tsv'
    if not corpus.is_file():
        nested = target / target.name
        corpus = nested / 'corpus.jsonl'
        queries = nested / 'queries.jsonl'
        qrels = nested / 'qrels' / 'test.tsv'
    return corpus.is_file() and queries.is_file() and qrels.is_file()

def _heal_marker(target: Path, *, name: str, url: str, md5: str) -> None:
    marker = target / '.pulled.json'
    if marker.is_file():
        return
    marker.write_text(json.dumps({'name': name, 'url': url, 'md5': md5, 'healed': True}, indent=2), encoding='utf-8')

def pull_beir(cfg: dict[str, Any] | None=None, *, force: bool=False) -> Path:
    ensure_data_dir()
    suites = cfg or load_suites()
    retrieval = suites['suites']['retrieval']
    root = suite_data('beir')
    root.mkdir(parents=True, exist_ok=True)
    _log(f'[pull] BENCH_DATA_DIR={data_dir()}')
    meta: dict[str, Any] = {'datasets': []}
    datasets = list(retrieval['datasets'])
    n = len(datasets)
    need: list[dict[str, Any]] = []
    cached_names: list[str] = []
    for ds in datasets:
        name = ds['name']
        target = root / name
        if not force and _beir_dataset_ready(target):
            _heal_marker(target, name=name, url=ds['url'], md5=ds.get('md5') or '')
            cached_names.append(name)
        else:
            need.append(ds)
    approx = sum((float(d.get('approx_mib') or 0) for d in need))
    _log(f'[pull] plan BEIR: {n} datasets · {len(cached_names)} cached · {len(need)} to download' + (f' · ~{approx:.0f} MiB remaining' if need else ' · nothing to fetch') + (f" · skip: {', '.join(cached_names)}" if cached_names else ''))
    _log(f'[progress] pull plan total={n} cached={len(cached_names)} need={len(need)} approx_mib={approx:.1f}')
    for (i, ds) in enumerate(datasets, start=1):
        name = ds['name']
        target = root / name
        zip_path = root / f'{name}.zip'
        label = f'dataset {i}/{n} {name}'
        if not force and _beir_dataset_ready(target):
            _heal_marker(target, name=name, url=ds['url'], md5=ds.get('md5') or '')
            _log(f'[pull] {label}: cached — skip')
            _log(f'[progress] pull dataset={i}/{n} file={name} pct=100 cached=1')
            meta['datasets'].append({'name': name, 'path': str(target), 'cached': True})
            continue
        if force and target.exists():
            shutil.rmtree(target)
        part = zip_path.with_suffix(zip_path.suffix + '.part')
        if part.exists():
            part.unlink()
        approx_one = float(ds.get('approx_mib') or 0)
        _log(f'[pull] {label}: downloading' + (f' (~{approx_one:.1f} MiB)' if approx_one else '') + '…')
        _download(ds['url'], zip_path, label=label, dataset_i=i, dataset_n=n)
        expect = (ds.get('md5') or '').lower()
        if expect:
            got = _md5_file(zip_path)
            if got != expect:
                raise RuntimeError(f'md5 mismatch for {name}: {got} != {expect}')
        _log(f'[pull] {label}: unzip {zip_path.name}')
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(root)
        if not target.exists():
            raise RuntimeError(f'expected extracted dir missing: {target}')
        if not _beir_dataset_ready(target):
            raise RuntimeError(f'BEIR extract incomplete for {name} under {target}')
        _heal_marker(target, name=name, url=ds['url'], md5=expect)
        _log(f'[progress] pull dataset={i}/{n} file={name} pct=100 cached=0')
        meta['datasets'].append({'name': name, 'path': str(target), 'cached': False})
    (root / 'pull_manifest.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    _log(f'[pull] BEIR ready under {root}')
    return root
_LONGBENCH_DATA_ZIP_DEFAULT = 'https://huggingface.co/datasets/THUDM/LongBench/resolve/main/data.zip'
_LONGBENCH_HF_PARQUET_FALLBACK = 'GinkgoQ/LongBench'

def _normalize_longbench_row(task: str, idx: int, row: dict[str, Any]) -> dict[str, Any]:
    """Map a LongBench record into the official-bench slice schema."""
    return {'task': task, 'idx': idx, 'input': row.get('input') or row.get('context') or '', 'context': row.get('context') or '', 'question': row.get('input') or row.get('question') or '', 'answers': row.get('answers') if row.get('answers') is not None else row.get('answer'), 'length': row.get('length'), 'dataset': row.get('dataset') or task, 'language': row.get('language') or 'en', 'all_classes': row.get('all_classes'), '_raw_keys': sorted(list(row.keys()))}

def _read_longbench_task_jsonl(path: Path, *, task: str, max_n: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            if not isinstance(raw, dict):
                continue
            rows.append(_normalize_longbench_row(task, len(rows), raw))
            if len(rows) >= max_n:
                break
    return rows

def _longbench_jsonl_path(extract_root: Path, task: str) -> Path | None:
    """Locate ``<task>.jsonl`` under a data.zip extract (layout may nest once)."""
    candidates = [extract_root / 'data' / f'{task}.jsonl', extract_root / f'{task}.jsonl', extract_root / 'data' / 'data' / f'{task}.jsonl']
    for p in candidates:
        if p.is_file():
            return p
    for base in (extract_root, extract_root / 'data'):
        if not base.is_dir():
            continue
        hit = base / f'{task}.jsonl'
        if hit.is_file():
            return hit
    return None

def _pull_longbench_from_zip(root: Path, ctx: dict[str, Any], *, force: bool) -> list[dict[str, Any]]:
    """Official path: download THUDM data.zip and slice task JSONL files.

    Avoids ``load_dataset('THUDM/LongBench', …)`` which fails on datasets≥4
    (remote dataset scripts removed).
    """
    max_n = int(ctx.get('max_samples_per_task') or 40)
    tasks = list(ctx['tasks'])
    zip_url = (ctx.get('hf_data_zip') or _LONGBENCH_DATA_ZIP_DEFAULT).strip()
    zip_path = root / 'data.zip'
    extract_root = root / 'raw'
    _log(f'[pull] plan LongBench: {len(tasks)} tasks · ≤{max_n} samples each · zip {zip_url}')

    def _tasks_ready() -> bool:
        return extract_root.is_dir() and all((_longbench_jsonl_path(extract_root, t) is not None for t in tasks))
    need_download = force or not zip_path.is_file()
    need_unzip = force or not _tasks_ready()
    if need_download:
        if force and extract_root.exists():
            shutil.rmtree(extract_root)
        part = zip_path.with_suffix(zip_path.suffix + '.part')
        if part.exists():
            part.unlink()
        _log('[pull] downloading LongBench data.zip…')
        _download(zip_url, zip_path, label='longbench data.zip', dataset_i=1, dataset_n=1)
        need_unzip = True
    else:
        _log(f'[pull] longbench zip cached → {zip_path}')
    if need_unzip:
        if extract_root.exists():
            shutil.rmtree(extract_root)
        extract_root.mkdir(parents=True, exist_ok=True)
        _log(f'[pull] unzip {zip_path.name}')
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_root)
    else:
        _log(f'[pull] longbench extract cached → {extract_root}')
    rows: list[dict[str, Any]] = []
    for (ti, task) in enumerate(tasks, start=1):
        _log(f'[pull] dataset {ti}/{len(tasks)} {task}')
        _log(f'[progress] pull dataset={ti}/{len(tasks)} file={task} pct=0')
        path = _longbench_jsonl_path(extract_root, task)
        if path is None:
            raise RuntimeError(f'LongBench task file missing after unzip: {task}.jsonl under {extract_root}')
        task_rows = _read_longbench_task_jsonl(path, task=task, max_n=max_n)
        if not task_rows:
            raise RuntimeError(f'LongBench task empty: {path}')
        rows.extend(task_rows)
        _log(f'[progress] pull dataset={ti}/{len(tasks)} file={task} pct=100')
    return rows

def _pull_longbench_via_datasets(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Fallback when zip pull is unavailable (offline mirror / old cache)."""
    try:
        from datasets import load_dataset
    except ImportError as e:
        raise SystemExit('LongBench pull needs a networkable data.zip or `datasets`. pip install -r eval/official/requirements.txt') from e
    max_n = int(ctx.get('max_samples_per_task') or 40)
    tasks = list(ctx['tasks'])
    primary = (ctx.get('hf_dataset') or 'THUDM/LongBench').strip()
    parquet_fallback = (ctx.get('hf_dataset_parquet') or _LONGBENCH_HF_PARQUET_FALLBACK).strip()
    revision = ctx.get('hf_revision') or 'main'
    candidates = [primary]
    if parquet_fallback and parquet_fallback not in candidates:
        candidates.append(parquet_fallback)
    last_err: BaseException | None = None
    for repo in candidates:
        _log(f'[pull] plan LongBench (datasets fallback): {len(tasks)} tasks · ≤{max_n} samples · HF {repo}')
        rows: list[dict[str, Any]] = []
        try:
            for (ti, task) in enumerate(tasks, start=1):
                _log(f'[pull] dataset {ti}/{len(tasks)} {task}')
                _log(f'[progress] pull dataset={ti}/{len(tasks)} file={task} pct=0')
                try:
                    ds = load_dataset(repo, task, split='test', revision=revision, trust_remote_code=True)
                except TypeError:
                    ds = load_dataset(repo, task, split='test', revision=revision)
                for (i, row) in enumerate(ds):
                    if i >= max_n:
                        break
                    rows.append(_normalize_longbench_row(task, i, dict(row)))
                _log(f'[progress] pull dataset={ti}/{len(tasks)} file={task} pct=100')
            return rows
        except Exception as e:
            last_err = e
            _log(f'[pull] datasets fallback {repo} failed: {e}')
            continue
    assert last_err is not None
    raise last_err

def pull_longbench(cfg: dict[str, Any] | None=None, *, force: bool=False) -> Path:
    ensure_data_dir()
    suites = cfg or load_suites()
    ctx = suites['suites']['context']
    root = suite_data('longbench')
    root.mkdir(parents=True, exist_ok=True)
    out_file = root / 'small_slice.jsonl'
    marker = root / '.pulled.json'
    if out_file.exists() and marker.exists() and (not force):
        _log(f'[pull] longbench: cached → {out_file}')
        _log('[progress] pull dataset=1/1 file=longbench pct=100 cached=1')
        return root
    rows: list[dict[str, Any]]
    source = 'zip'
    try:
        rows = _pull_longbench_from_zip(root, ctx, force=force)
    except Exception as zip_err:
        _log(f'[pull] LongBench zip path failed ({zip_err}); trying datasets…')
        rows = _pull_longbench_via_datasets(ctx)
        source = 'datasets'
    with out_file.open('w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    marker.write_text(json.dumps({'hf_dataset': ctx.get('hf_dataset'), 'hf_data_zip': ctx.get('hf_data_zip') or _LONGBENCH_DATA_ZIP_DEFAULT, 'source': source, 'tasks': ctx['tasks'], 'max_samples_per_task': int(ctx.get('max_samples_per_task') or 40), 'n_rows': len(rows)}, indent=2), encoding='utf-8')
    _log(f'[pull] longbench wrote {len(rows)} rows → {out_file} (source={source})')
    return root

def pull_swebench(cfg: dict[str, Any] | None=None, *, force: bool=False) -> Path:
    ensure_data_dir()
    suites = cfg or load_suites()
    coding = suites['suites']['coding']
    root = suite_data('swebench_lite')
    root.mkdir(parents=True, exist_ok=True)
    out_file = root / 'instances.jsonl'
    marker = root / '.pulled.json'
    if out_file.exists() and marker.exists() and (not force):
        _log(f'[pull] swebench_lite: cached → {out_file}')
        _log('[progress] pull dataset=1/1 file=swebench_lite pct=100 cached=1')
        return root
    try:
        from datasets import load_dataset
    except ImportError as e:
        raise SystemExit('SWE-bench pull needs `datasets`. pip install -r eval/official/requirements.txt') from e
    _log('[progress] pull plan total=1 cached=0 need=1 approx_mib=0')
    _log(f"[pull] {coding['hf_dataset']} split={coding.get('split', 'test')}")
    _log('[progress] pull dataset=1/1 file=swebench_lite pct=0')
    ds = load_dataset(coding['hf_dataset'], split=coding.get('split') or 'test', revision=coding.get('hf_revision') or 'main')
    max_n = int(coding.get('max_instances') or 0)
    n = 0
    with out_file.open('w', encoding='utf-8') as f:
        for row in ds:
            f.write(json.dumps(dict(row), ensure_ascii=False) + '\n')
            n += 1
            if max_n and n >= max_n:
                break
    marker.write_text(json.dumps({'hf_dataset': coding['hf_dataset'], 'split': coding.get('split'), 'n_instances': n}, indent=2), encoding='utf-8')
    _log(f'[pull] swebench_lite wrote {n} instances → {out_file}')
    _log('[progress] pull dataset=1/1 file=swebench_lite pct=100 cached=0')
    return root

def pull_all(*, force: bool=False) -> dict[str, str]:
    ensure_dirs()
    ensure_data_dir()
    cfg = load_suites()
    beir = pull_beir(cfg, force=force)
    lb = pull_longbench(cfg, force=force)
    swe = pull_swebench(cfg, force=force)
    return {'beir': str(beir), 'longbench': str(lb), 'swebench_lite': str(swe)}
