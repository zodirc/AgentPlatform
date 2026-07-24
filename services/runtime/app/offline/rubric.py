from __future__ import annotations

import re
from typing import Sequence


# Common AI-taste / filler phrases (offline only; docs/14 WQ4).
_AI_BAN_PHRASES = (
    "在这个时代",
    "不禁",
    "充满了",
    "值得一提的是",
    "总而言之",
    "综上所述",
    "不可否认",
    "as an ai",
    "as a language model",
)

# Meta-knowing / summary-voice families from writing/system.md Ban list (docs/30 WN2).
_META_KNOWING_PHRASES = (
    "他知道",
    "她知道",
    "他明白",
    "她明白",
    "他意识到",
    "她意识到",
    "心里清楚",
    "心知肚明",
    "她忽然懂了",
    "他忽然懂了",
    "不禁想到",
    "忽然觉得",
    "一种说不清的情绪",
    "仿佛一切尽在掌握",
    "两人之间的空气凝固了",
)

# Glue phrases (docs/30 WN2 / writing system.md Also avoid).
_GLUE_PHRASES = (
    "与此同时",
    "就在这时",
    "不仅如此",
    "总而言之",
    "综上所述",
)

# Rough dialogue / action cues vs synopsis cues (heuristic only).
_DIALOGUE_OR_ACTION = re.compile(
    r'[「」『』“”"].+|说道|问道|答道|点了点头|摇了摇头|转身|推门|拔刀|拔枪'
)
_SYNOPSIS_CUE = re.compile(
    r"后来|于是|终于|总之|由此可见|这一章|本章讲述|概括|总结起来"
)


def score_rubric(text: str) -> dict:
    """Heuristic fidelity / structure / style scores in [0, 1] (docs/13 S3 A5; docs/14 WQ4).

    Offline / sample only — never invoke on the turn hot path.
    Also reports WN2 dimensions: meta_knowing_rate, glue_rate, scene_ratio.
    """
    stripped = text.strip()
    length = len(stripped)
    structure = 0.4
    if re.search(r"^#{1,3}\s", stripped, re.M) or "\n- " in stripped or "\n1. " in stripped:
        structure += 0.3
    if length > 80:
        structure += 0.2
    # Penalize heading level jumps (same idea as export lint).
    levels = [len(m.group(1)) for m in re.finditer(r"^(#{1,6})\s+", stripped, re.M)]
    for prev, cur in zip(levels, levels[1:]):
        if cur > prev + 1:
            structure = max(0.0, structure - 0.2)
            break
    structure = min(structure, 1.0)

    fidelity = 0.5
    if "cite:" in stripped or "sources/" in stripped:
        fidelity += 0.2
    if not re.search(r"\bTODO\b|\bTBD\b|\blorem ipsum\b", stripped, re.I):
        fidelity += 0.2
    if re.search(r"\[cite:\s*\]", stripped):
        fidelity = max(0.0, fidelity - 0.3)
    fidelity = min(fidelity, 1.0)

    style = 0.5
    if length > 40:
        style += 0.2
    if not re.search(r"[！？]{3,}|!!!+", stripped):
        style += 0.2
    lowered = stripped.lower()
    ban_hits = [p for p in _AI_BAN_PHRASES if p in lowered or p in stripped]
    if ban_hits:
        style = max(0.0, style - 0.15 * min(len(ban_hits), 3))

    meta_hits = [p for p in _META_KNOWING_PHRASES if p in stripped]
    glue_hits = [p for p in _GLUE_PHRASES if p in stripped]
    # Density ≈ hits per 500 chars (cap at 1.0).
    denom = max(length / 500.0, 1.0)
    meta_knowing_rate = min(1.0, len(meta_hits) / denom)
    glue_rate = min(1.0, len(glue_hits) / denom)
    if meta_hits:
        style = max(0.0, style - 0.1 * min(len(meta_hits), 3))
    if glue_hits:
        style = max(0.0, style - 0.08 * min(len(glue_hits), 3))
    style = min(style, 1.0)

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", stripped) if p.strip()] or (
        [stripped] if stripped else []
    )
    scene_hits = sum(1 for p in paragraphs if _DIALOGUE_OR_ACTION.search(p))
    synopsis_hits = sum(1 for p in paragraphs if _SYNOPSIS_CUE.search(p))
    if not paragraphs:
        scene_ratio = 0.0
    else:
        # Prefer dialogue/action; synopsis-heavy paragraphs pull the ratio down.
        scene_ratio = round(
            max(0.0, min(1.0, (scene_hits - 0.5 * synopsis_hits) / len(paragraphs))),
            4,
        )

    overall = round((fidelity + structure + style) / 3.0, 4)
    return {
        "fidelity": round(fidelity, 4),
        "structure": round(structure, 4),
        "style": round(style, 4),
        "overall": overall,
        "scorer": "heuristic",
        "ban_hits": ban_hits,
        "meta_hits": meta_hits,
        "glue_hits": glue_hits,
        "meta_knowing_rate": round(meta_knowing_rate, 4),
        "glue_rate": round(glue_rate, 4),
        "scene_ratio": scene_ratio,
    }


def score_code_rubric(
    *,
    tool_names: Sequence[str],
    old_text: str = "",
    new_text: str = "",
    whole_file_write: bool = False,
) -> dict:
    """Offline code-edit quality heuristics (docs/30 CQ3). Never on the hot path.

    Dimensions (higher is better unless noted):
    - lint_followed: write/edit/patch followed later by read_lints
    - tests_followed: write tools followed later by run_tests (soft; 1.0 if no write)
    - minimal_diff: surgical span vs whole-file rewrite
    - re_read_before_retry: if propose_patch appears twice, a read_file sits between
    - single_edit_path: penalize propose_patch + edit_file churn in one turn
    - read_thrift: penalize excessive read_file calls (post-complete paging proxy)
    """
    names = [str(n) for n in tool_names]
    write_tools = {"write_file", "edit_file", "propose_patch"}
    write_idxs = [i for i, n in enumerate(names) if n in write_tools]
    lint_idxs = [i for i, n in enumerate(names) if n == "read_lints"]
    test_idxs = [i for i, n in enumerate(names) if n == "run_tests"]
    read_idxs = [i for i, n in enumerate(names) if n == "read_file"]

    if not write_idxs:
        lint_followed = 1.0
        tests_followed = 1.0
    else:
        last_write = write_idxs[-1]
        lint_followed = 1.0 if any(i > last_write for i in lint_idxs) else 0.0
        tests_followed = 1.0 if any(i > last_write for i in test_idxs) else 0.5

    if whole_file_write or (old_text and new_text and old_text.strip() == new_text.strip()):
        # Identical "rewrite" or explicit whole-file flag → not minimal.
        minimal_diff = 0.2 if whole_file_write else 0.5
    elif old_text and new_text:
        # Span size relative to file: smaller replacement → higher score.
        base = max(len(old_text), 1)
        ratio = abs(len(new_text) - len(old_text)) / base
        # Also penalize replacing nearly the entire file content.
        cover = len(old_text) / max(len(old_text), len(new_text), 1)
        minimal_diff = max(0.0, min(1.0, 1.0 - min(ratio, 1.0) * 0.5 - (0.4 if cover > 0.85 and len(old_text) > 200 else 0.0)))
    else:
        # Unknown span — reward propose_patch/edit_file over write_file.
        if "write_file" in names and "propose_patch" not in names and "edit_file" not in names:
            minimal_diff = 0.3
        elif "propose_patch" in names or "edit_file" in names:
            minimal_diff = 0.8
        else:
            minimal_diff = 0.5

    patch_idxs = [i for i, n in enumerate(names) if n == "propose_patch"]
    if len(patch_idxs) < 2:
        re_read_before_retry = 1.0
    else:
        ok = True
        for a, b in zip(patch_idxs, patch_idxs[1:]):
            if not any(a < r < b for r in read_idxs):
                ok = False
                break
        re_read_before_retry = 1.0 if ok else 0.0

    # Prefer a single apply path: edit_file XOR propose_patch (not both).
    has_propose = "propose_patch" in names
    has_edit = "edit_file" in names
    if has_propose and has_edit:
        single_edit_path = 0.25
    elif has_propose or has_edit or "write_file" in names:
        single_edit_path = 1.0
    else:
        single_edit_path = 1.0

    read_count = len(read_idxs)
    if read_count <= 2:
        read_thrift = 1.0
    elif read_count <= 4:
        read_thrift = 0.55
    elif read_count <= 8:
        read_thrift = 0.3
    else:
        read_thrift = 0.1

    overall = round(
        (
            lint_followed
            + tests_followed
            + minimal_diff
            + re_read_before_retry
            + single_edit_path
            + read_thrift
        )
        / 6.0,
        4,
    )
    return {
        "lint_followed": round(lint_followed, 4),
        "tests_followed": round(tests_followed, 4),
        "minimal_diff": round(minimal_diff, 4),
        "re_read_before_retry": round(re_read_before_retry, 4),
        "single_edit_path": round(single_edit_path, 4),
        "read_thrift": round(read_thrift, 4),
        "overall": overall,
        "scorer": "code_heuristic",
        "tool_names": names,
    }
