#!/usr/bin/env python3
"""Fetch + convert intel standing corpus into seed/sources/intel/vendor (Turn 外).

Reads ``seed/sources/intel/SOURCES.yaml``. Never runs on the Agent hot path.

Examples:
  python3 scripts/intel_corpus_fetch.py --dry-run
  python3 scripts/intel_corpus_fetch.py
  python3 scripts/intel_corpus_fetch.py --only threat-hunter,atomic-red-team
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    print("pyyaml required: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "seed" / "sources" / "intel" / "SOURCES.yaml"

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _slug(text: str, *, max_len: int = 80) -> str:
    s = _SLUG_RE.sub("-", (text or "").strip()).strip("-_.")
    return (s or "item")[:max_len]


def _load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"invalid manifest: {path}")
    return data


def _dir_bytes(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                continue
    return total


def _matches_any(rel: str, patterns: list[str]) -> bool:
    rel = rel.replace("\\", "/")
    return any(fnmatch.fnmatch(rel, pat) for pat in patterns)


def _is_forbidden(name: str, forbidden: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in forbidden)


def _git_shallow_clone(
    repo: str,
    dest: Path,
    *,
    ref: str,
    sparse: list[str],
    sparse_cone: bool = True,
) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    cmd = ["git", "clone", "--depth", "1", "--filter=blob:none"]
    if sparse:
        cmd.append("--sparse")
    if ref:
        cmd.extend(["--branch", ref])
    cmd.extend([repo, str(dest)])
    subprocess.run(cmd, check=True, cwd=str(ROOT))
    if sparse:
        if sparse_cone:
            subprocess.run(
                ["git", "sparse-checkout", "set", *sparse],
                check=True,
                cwd=str(dest),
            )
        else:
            subprocess.run(
                ["git", "sparse-checkout", "set", "--no-cone", *sparse],
                check=True,
                cwd=str(dest),
            )
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=str(dest),
        text=True,
    ).strip()
    return sha


def _clear_dest(dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)


def _copy_filtered(
    repo_dir: Path,
    dest: Path,
    *,
    include_globs: list[str],
    exclude_globs: list[str],
    forbidden: list[str],
    max_files: int | None,
) -> int:
    _clear_dest(dest)
    copied = 0
    for path in sorted(repo_dir.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        rel = path.relative_to(repo_dir).as_posix()
        if include_globs and not _matches_any(rel, include_globs):
            continue
        if exclude_globs and _matches_any(rel, exclude_globs):
            continue
        if _is_forbidden(path.name, forbidden):
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)
        copied += 1
        if max_files is not None and copied >= max_files:
            break
    return copied


def _galaxy_to_md(
    repo_dir: Path,
    dest: Path,
    *,
    options: dict[str, Any],
    forbidden: list[str],
) -> int:
    _clear_dest(dest)
    clusters = repo_dir / "clusters"
    if not clusters.is_dir():
        return 0
    prefer = list(options.get("prefer_clusters") or [])
    max_files = int(options.get("max_files") or 800)
    max_desc = int(options.get("max_desc_chars") or 1200)

    files = sorted(clusters.glob("*.json"))
    preferred = [clusters / name for name in prefer if (clusters / name).is_file()]
    rest = [p for p in files if p not in preferred]
    ordered = preferred + rest

    written = 0
    for cluster_path in ordered:
        if _is_forbidden(cluster_path.name, forbidden):
            continue
        try:
            data = json.loads(cluster_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cluster_name = str(data.get("name") or cluster_path.stem)
        values = data.get("values") or []
        if not isinstance(values, list):
            continue
        for idx, val in enumerate(values):
            if written >= max_files:
                return written
            if not isinstance(val, dict):
                continue
            title = str(val.get("value") or val.get("uuid") or f"item-{idx}")
            desc = str(val.get("description") or "").strip()
            if len(desc) > max_desc:
                desc = desc[: max_desc - 1] + "…"
            meta = val.get("meta") or {}
            synonyms = []
            if isinstance(meta, dict):
                syn = meta.get("synonyms") or meta.get("alias") or []
                if isinstance(syn, list):
                    synonyms = [str(x) for x in syn[:12]]
            slug = _slug(f"{cluster_path.stem}-{title}")
            body = [
                f"# {title}",
                "",
                f"> 类型: intel-galaxy",
                f"> cluster: {cluster_name}",
                f"> tags: {cluster_path.stem}",
                f"> license: CC0-or-BSD (MISP Galaxy)",
                "",
                "## Summary",
                "",
                desc or "_No description in galaxy entry._",
                "",
            ]
            if synonyms:
                body.extend(["## Aliases", "", ", ".join(synonyms), ""])
            body.extend(
                [
                    "## Source",
                    "",
                    f"Converted from MISP Galaxy cluster `{cluster_path.name}`.",
                    "",
                ]
            )
            out = dest / cluster_path.stem / f"{slug}.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("\n".join(body), encoding="utf-8")
            written += 1
    return written


def _attack_to_md(
    repo_dir: Path,
    dest: Path,
    *,
    options: dict[str, Any],
    forbidden: list[str],
) -> int:
    _clear_dest(dest)
    bundle_name = str(options.get("bundle_name") or "enterprise-attack.json")
    bundle = repo_dir / "enterprise-attack" / bundle_name
    if not bundle.is_file():
        # fallback: first enterprise-attack*.json that is exactly the rolling name
        candidates = sorted((repo_dir / "enterprise-attack").glob("enterprise-attack.json"))
        if not candidates:
            return 0
        bundle = candidates[0]
    if _is_forbidden(bundle.name, forbidden):
        return 0
    data = json.loads(bundle.read_text(encoding="utf-8"))
    objects = data.get("objects") if isinstance(data, dict) else data
    if not isinstance(objects, list):
        return 0
    want = set(options.get("types") or ["attack-pattern"])
    max_files = int(options.get("max_files") or 1200)
    max_desc = int(options.get("max_desc_chars") or 2000)
    written = 0
    for obj in objects:
        if written >= max_files:
            break
        if not isinstance(obj, dict):
            continue
        otype = str(obj.get("type") or "")
        if otype not in want:
            continue
        name = str(obj.get("name") or obj.get("id") or "unnamed")
        ext_ids = obj.get("external_references") or []
        attack_id = ""
        for ref in ext_ids:
            if isinstance(ref, dict) and ref.get("source_name") == "mitre-attack":
                attack_id = str(ref.get("external_id") or "")
                break
        desc = str(obj.get("description") or "").strip()
        if len(desc) > max_desc:
            desc = desc[: max_desc - 1] + "…"
        slug = _slug(f"{attack_id or otype}-{name}")
        body = [
            f"# {name}",
            "",
            f"> 类型: intel-attack",
            f"> stix_type: {otype}",
            f"> attack_id: {attack_id or 'n/a'}",
            f"> tags: mitre-attack, {otype}",
            f"> license: MITRE-custom (retain copyright notice)",
            "",
            "## Summary",
            "",
            desc or "_No description._",
            "",
            "## Source",
            "",
            f"Converted from `{bundle.name}` object `{obj.get('id', '')}`.",
            "",
        ]
        out = dest / otype / f"{slug}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(body), encoding="utf-8")
        written += 1
    # Keep MITRE license notice beside converted corpus
    notice = dest / "LICENSE-MITRE.txt"
    notice.write_text(
        "ATT&CK content © The MITRE Corporation. Use under the MITRE ATT&CK license "
        "(royalty-free; retain copyright designation). See upstream LICENSE.txt.\n",
        encoding="utf-8",
    )
    return written


def _unit42_ioc_cards(
    repo_dir: Path,
    dest: Path,
    *,
    options: dict[str, Any],
    forbidden: list[str],
) -> int:
    _clear_dest(dest)
    max_card = int(options.get("max_card_bytes") or 200_000)
    max_files = int(options.get("max_files") or 200)
    written = 0
    for path in sorted(repo_dir.rglob("*")):
        if written >= max_files:
            break
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.suffix.lower() not in {".json", ".txt"}:
            continue
        if _is_forbidden(path.name, forbidden):
            continue
        # Skip obvious bulky dumps
        low = path.name.lower()
        if any(x in low for x in ("sample", "encodedcommand", "golang_malware_results")):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size <= 0 or size > max_card:
            continue
        rel = path.relative_to(repo_dir).as_posix()
        # Prefer small structured JSON as enrich cards when they look like a single IOC
        if path.suffix.lower() == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            cards: list[dict[str, Any]] = []
            if isinstance(data, dict) and (data.get("indicator") or data.get("normalized")):
                cards = [data]
            elif isinstance(data, list):
                for item in data[:50]:
                    if isinstance(item, dict) and (item.get("indicator") or item.get("value")):
                        ind = str(item.get("indicator") or item.get("value"))
                        cards.append(
                            {
                                "indicator": ind,
                                "normalized": ind,
                                "type": item.get("type") or "unknown",
                                "reputation_stub": item.get("reputation_stub") or "unknown",
                                "tags": list(item.get("tags") or ["unit42"]),
                                "related": list(item.get("related") or []),
                                "sources": [f"unit42:{rel}"],
                                "raw_ref": f"sources/seed/intel/vendor/ioc/{_slug(ind)}.json",
                                "summary": str(item.get("summary") or item.get("description") or ind)[:400],
                            }
                        )
            for card in cards:
                ind = str(card.get("indicator") or "").strip()
                if not ind:
                    continue
                out = dest / f"{_slug(ind)}.json"
                if out.exists():
                    continue
                out.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                written += 1
                if written >= max_files:
                    break
            continue
        # .txt lists → one markdown note pointing at first lines (not full dump)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        preview = lines[:40]
        if not preview:
            continue
        title = path.stem
        body = [
            f"# Unit 42 IoC list: {title}",
            "",
            f"> 类型: intel-ioc-list",
            f"> tags: unit42, ioc",
            f"> license: MIT",
            "",
            "## Summary",
            "",
            f"Excerpt from `{rel}` ({len(lines)} non-empty lines in source; showing ≤40).",
            "",
            "## Indicators (preview)",
            "",
            *[f"- `{ln}`" for ln in preview],
            "",
            "## Source",
            "",
            "Converted from pan-unit42/iocs (MIT).",
            "",
        ]
        out = dest / "lists" / f"{_slug(title)}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(body), encoding="utf-8")
        written += 1
    return written


CONVERTERS = {
    "copy_filtered": _copy_filtered,
    "galaxy_to_md": _galaxy_to_md,
    "attack_to_md": _attack_to_md,
    "unit42_ioc_cards": _unit42_ioc_cards,
}


def fetch_one(
    src: dict[str, Any],
    *,
    cache_root: Path,
    vendor_root: Path,
    forbidden: list[str],
    dry_run: bool,
) -> dict[str, Any]:
    sid = str(src["id"])
    convert = str(src.get("convert") or "copy_filtered")
    dest = vendor_root / str(src.get("dest") or sid)
    info: dict[str, Any] = {
        "id": sid,
        "license": src.get("license"),
        "repo": src.get("repo"),
        "convert": convert,
        "dest": str(dest.relative_to(ROOT)) if dest.is_relative_to(ROOT) else str(dest),
    }
    if dry_run:
        info["status"] = "dry-run"
        return info

    repo_dir = cache_root / sid
    print(f"==> clone {sid}")
    sha = _git_shallow_clone(
        str(src["repo"]),
        repo_dir,
        ref=str(src.get("ref") or ""),
        sparse=list(src.get("sparse") or []),
        sparse_cone=bool(src.get("sparse_cone", True)),
    )
    info["sha"] = sha
    options = dict(src.get("options") or {})
    max_files = options.get("max_files")
    max_files_i = int(max_files) if max_files is not None else None

    print(f"==> convert {sid} → {dest}")
    if convert == "copy_filtered":
        n = _copy_filtered(
            repo_dir,
            dest,
            include_globs=list(src.get("include_globs") or ["**/*"]),
            exclude_globs=list(src.get("exclude_globs") or []),
            forbidden=forbidden,
            max_files=max_files_i,
        )
    elif convert == "galaxy_to_md":
        n = _galaxy_to_md(repo_dir, dest, options=options, forbidden=forbidden)
    elif convert == "attack_to_md":
        n = _attack_to_md(repo_dir, dest, options=options, forbidden=forbidden)
    elif convert == "unit42_ioc_cards":
        n = _unit42_ioc_cards(repo_dir, dest, options=options, forbidden=forbidden)
    else:
        raise SystemExit(f"unknown convert: {convert}")
    info["files_written"] = n
    info["status"] = "ok"
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated source ids (default: all enabled)",
    )
    parser.add_argument(
        "--keep-cache",
        action="store_true",
        help="Keep .cache/intel-corpus clones (default: keep)",
    )
    args = parser.parse_args(argv)

    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    cfg = _load_manifest(manifest_path)
    vendor_root = ROOT / str(cfg.get("vendor_root") or "seed/sources/intel/vendor")
    cache_root = ROOT / str(cfg.get("cache_root") or ".cache/intel-corpus")
    max_vendor = int(cfg.get("max_vendor_bytes") or 157_286_400)
    forbidden = list(cfg.get("forbidden_globs") or [])
    only = {x.strip() for x in args.only.split(",") if x.strip()}

    sources = [s for s in (cfg.get("sources") or []) if isinstance(s, dict)]
    selected = []
    for s in sources:
        if only and s.get("id") not in only:
            continue
        if not only and not s.get("enabled", True):
            continue
        selected.append(s)

    if not selected:
        print("no sources selected", file=sys.stderr)
        return 2

    print(f"manifest={manifest_path.relative_to(ROOT)}")
    print(f"vendor_root={vendor_root.relative_to(ROOT)} max={max_vendor / 1024 / 1024:.0f}MiB")
    print(f"sources={[s['id'] for s in selected]}")

    if args.dry_run:
        for s in selected:
            print(json.dumps(fetch_one(s, cache_root=cache_root, vendor_root=vendor_root, forbidden=forbidden, dry_run=True)))
        return 0

    vendor_root.mkdir(parents=True, exist_ok=True)
    # Preserve .gitkeep; clear previous converted trees for selected dests only
    results = []
    for s in selected:
        results.append(
            fetch_one(
                s,
                cache_root=cache_root,
                vendor_root=vendor_root,
                forbidden=forbidden,
                dry_run=False,
            )
        )
        used = _dir_bytes(vendor_root)
        print(f"vendor size now: {used / 1024 / 1024:.1f} MiB")
        if used > max_vendor:
            print(
                f"ERROR: vendor exceeded max_vendor_bytes ({used} > {max_vendor})",
                file=sys.stderr,
            )
            return 1

    manifest_out = {
        "generated_by": "scripts/intel_corpus_fetch.py",
        "max_vendor_bytes": max_vendor,
        "vendor_bytes": _dir_bytes(vendor_root),
        "sources": results,
    }
    (vendor_root / "MANIFEST.json").write_text(
        json.dumps(manifest_out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {vendor_root / 'MANIFEST.json'}")
    print(f"done. vendor={manifest_out['vendor_bytes'] / 1024 / 1024:.1f} MiB")
    print("Next: make sync-sources  # if stack is up")
    _ = args.keep_cache  # cache kept by default; flag reserved
    return 0


if __name__ == "__main__":
    # Allow Path.is_relative_to on 3.9 via shim
    if not hasattr(Path, "is_relative_to"):

        def _is_relative_to(self: Path, other: Path) -> bool:  # type: ignore[misc]
            try:
                self.relative_to(other)
                return True
            except ValueError:
                return False

        Path.is_relative_to = _is_relative_to  # type: ignore[attr-defined]

    raise SystemExit(main())
