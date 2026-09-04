"""平台 markdown 范文库。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.writing.signals.signature import Vec, signature_vec
from app.writing.text_metrics import visible_chars

_EXEMPLAR_DIR = Path(__file__).resolve().parent / "exemplars"
_EXEMPLAR_WEB_SERIAL_DIR = Path(__file__).resolve().parent / "exemplars_web_serial"
_HEADING = re.compile(
    r"^(?P<author>[^《]+)《(?P<work>[^》]+)》(?:·(?P<beat>\S.*))?$"
)


@dataclass(frozen=True)
class Exemplar:
    """范文样本。
    
    参数:
        fragment/slug/author/work/beat/text/signature等。"""
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
        """范文 slug 别名。

        返回:
            与 ``slug`` 相同。
        """
        return self.slug

    @property
    def text_sha256(self) -> str:
        """范文原文 SHA-256 摘要。

        返回:
            hex digest 字符串。
        """
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


def load_exemplars_dir(
    directory: Path,
    *,
    scope: str = "platform",
) -> dict[str, tuple[Exemplar, ...]]:
    """解析范文目录。
    
    参数:
        directory/scope。
    
    返回:
        dict。"""
    bank: dict[str, list[Exemplar]] = {}
    if not directory.is_dir():
        return {}
    for path in sorted(directory.glob("*.md")):
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
                    scope=scope,
                )
            )
    return {k: tuple(v) for k, v in bank.items()}


@lru_cache(maxsize=4)
def load_platform_exemplars(work_mode: str = "literary") -> dict[str, tuple[Exemplar, ...]]:
    """平台范文（cached）。``work_mode=web_serial`` 换节奏库。"""
    from app.writing.signals.prefs_loader import _module as _writing_prefs

    mode = _writing_prefs().normalize_work_mode(work_mode)
    if mode == "web_serial" and _EXEMPLAR_WEB_SERIAL_DIR.is_dir():
        bank = load_exemplars_dir(_EXEMPLAR_WEB_SERIAL_DIR, scope="platform")
        if bank:
            return bank
    return load_exemplars_dir(_EXEMPLAR_DIR, scope="platform")


def iter_platform_exemplars() -> tuple[Exemplar, ...]:
    """迭代全部范文。

    参数:
        无。

    返回:
        tuple。"""
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


def find_platform_exemplar(
    *,
    slug: str,
    fragment: str | None = None,
    work_mode: str = "literary",
) -> Exemplar | None:
    """按 slug 查找。
    
    参数:
        slug/fragment/work_mode。
    
    返回:
        Exemplar|None。"""
    want = (slug or "").strip()
    if not want:
        return None
    frag = (fragment or "").strip() or None
    bank = load_platform_exemplars(work_mode)
    rows: tuple[Exemplar, ...]
    if frag:
        rows = bank.get(frag, ())
    else:
        rows = tuple(sample for samples in bank.values() for sample in samples)
    for sample in rows:
        if sample.slug == want:
            return sample
    if frag:
        for sample in (s for samples in bank.values() for s in samples):
            if sample.slug == want:
                return sample
    return None


def exemplar_lab_payload(sample: Exemplar) -> dict[str, str]:
    """Lab API payload。
    
    参数:
        sample。
    
    返回:
        dict。"""
    return {
        "fragment": sample.fragment,
        "slug": sample.slug,
        "author": sample.author,
        "work": sample.work,
        "beat": sample.beat,
        "license": sample.license,
        "text": sample.text,
    }
