"""Platform exemplar source of truth: git markdown (not RAG chunks)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.writing.signals.signature import Vec, signature_vec
from app.writing.text_metrics import visible_chars

_EXEMPLAR_DIR = Path(__file__).resolve().parent / "exemplars"
_HEADING = re.compile(
    r"^(?P<author>[^《]+)《(?P<work>[^》]+)》(?:·(?P<beat>\S.*))?$"
)


@dataclass(frozen=True)
class Exemplar:
    fragment: str
    slug: str
    author: str
    work: str
    beat: str
    text: str
    signature: Vec
    weight: float = 1.0
    scope: str = "platform"
    license: str = "public_domain"

    @property
    def sample_id(self) -> str:
        return self.slug

    @property
    def text_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    text = raw.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        fm[key.strip()] = val.strip()
    body = text[end + 4 :].lstrip("\n")
    return fm, body


def _blockquote_text(block: str) -> str:
    lines: list[str] = []
    for ln in block.splitlines():
        s = ln.strip()
        if s.startswith(">"):
            s = s[1:].strip()
        if s:
            lines.append(s)
    return "\n".join(lines)


def _slug(work: str, beat: str) -> str:
    beat_part = beat or "passage"
    return f"{work}:{beat_part}"


@lru_cache(maxsize=1)
def load_platform_exemplars() -> dict[str, tuple[Exemplar, ...]]:
    bank: dict[str, list[Exemplar]] = {}
    if not _EXEMPLAR_DIR.is_dir():
        return {}
    for path in sorted(_EXEMPLAR_DIR.glob("*.md")):
        fm, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        fragment = (fm.get("fragment") or path.stem).strip()
        license_ = (fm.get("license") or "public_domain").strip()
        chunks = re.split(r"\n(?=###\s)", body)
        for chunk in chunks:
            heading = ""
            rest = chunk
            if chunk.startswith("###"):
                first, _, rest = chunk.partition("\n")
                heading = first.replace("###", "", 1).strip()
            text = _blockquote_text(rest)
            if visible_chars(text) < 40:
                continue
            m = _HEADING.match(heading)
            author = (m.group("author").strip() if m else "")
            work = (m.group("work").strip() if m else heading or path.stem)
            beat = (m.group("beat") or "").strip() if m else ""
            bank.setdefault(fragment, []).append(
                Exemplar(
                    fragment=fragment,
                    slug=_slug(work, beat),
                    author=author,
                    work=work,
                    beat=beat,
                    text=text,
                    signature=signature_vec(text),
                    license=license_,
                    scope="platform",
                )
            )
    return {k: tuple(v) for k, v in bank.items()}


def iter_platform_exemplars() -> tuple[Exemplar, ...]:
    bank = load_platform_exemplars()
    rows: list[Exemplar] = []
    seen: set[tuple[str, str]] = set()
    from app.writing.signals.prefs_loader import _module as _writing_prefs

    order = list(_writing_prefs().FRAGMENT_TYPES)
    for frag in list(bank.keys()):
        if frag not in order:
            order.append(frag)
    for frag in order:
        for sample in bank.get(frag, ()):
            key = (sample.fragment, sample.slug)
            if key in seen:
                continue
            seen.add(key)
            rows.append(sample)
    return tuple(rows)


def find_platform_exemplar(*, slug: str, fragment: str | None = None) -> Exemplar | None:
    want = (slug or "").strip()
    if not want:
        return None
    frag = (fragment or "").strip() or None
    for sample in iter_platform_exemplars():
        if sample.slug != want:
            continue
        if frag and sample.fragment != frag:
            continue
        return sample
    return None


def exemplar_lab_payload(sample: Exemplar) -> dict[str, str]:
    return {
        "fragment": sample.fragment,
        "slug": sample.slug,
        "author": sample.author,
        "work": sample.work,
        "beat": sample.beat,
        "license": sample.license,
        "text": sample.text,
    }
