"""Writing fragment weights & signal prefs (account-scoped, cross-Work)."""

from __future__ import annotations

from typing import Any

FRAGMENT_TYPES: tuple[str, ...] = (
    "plot_progress",
    "worldview_texture",
    "climax_beat",
    "battle_action",
    "dialogue_dyad",
    "mixed",
)

# literary = 经典白话（人物/句味/环境托举）；web_serial = 连载网文（长纲拉力/钩子/台阶）
WORK_MODES: tuple[str, ...] = ("literary", "web_serial")
DEFAULT_WORK_MODE = "literary"

DIMENSIONS: tuple[str, ...] = (
    "structure",
    "character",
    "pacing",
    "voice",
    "exemplar_alignment",
)

PRESET_LABELS: tuple[str, ...] = (
    "balanced",
    "custom",
)

SCHEMA_VERSION = 2

SIGNAL_PENALTY_KEYS: tuple[str, ...] = (
    "hinge_dense",
    "staccato_uniform",
    "opening_institution",
    "lore_dump",
    "length_short",
    "meta_knowing_high",
    "glue_heavy",
    "fragment_mismatch",
    "serial_hook_flat",
)

SIGNAL_REWARD_KEYS: tuple[str, ...] = (
    "scene_ratio_high",
    "dialogue_rhythm_varied",
    "exemplar_alignment_high",
    "outline_duty_match",
    "character_card_action",
    "plot_step_visible",
)

# Platform catalog (must match runtime markdown headings). Rhythm/texture only.
# 路遥《平凡的世界》（1992 逝世）不是伯尔尼公约自动公版；仅作节奏原型，不进 builtin voice 样品。
EXEMPLAR_CATALOG: dict[str, tuple[dict[str, str], ...]] = {
    "worldview_texture": (
        {"author": "鲁迅", "work": "孔乙己", "beat": "酒店格局"},
        {"author": "鲁迅", "work": "故乡", "beat": "忙月"},
        {"author": "鲁迅", "work": "从百草园到三味书屋", "beat": "百草园"},
        {"author": "鲁迅", "work": "社戏", "beat": "船头清香"},
    ),
    "dialogue_dyad": (
        {"author": "郁达夫", "work": "春风沉醉的晚上", "beat": "问找不到事"},
        {"author": "鲁迅", "work": "故乡", "beat": "杨二嫂讨木器"},
        {"author": "鲁迅", "work": "孔乙己", "beat": "茴香豆"},
        {"author": "鲁迅", "work": "阿Q正传", "beat": "小尼姑"},
        {"author": "老舍", "work": "骆驼祥子", "beat": "虎妞拉话"},
        {"author": "老舍", "work": "骆驼祥子", "beat": "刘四爷问车"},
        {"author": "老舍", "work": "茶馆", "beat": "王利发招呼"},
        {"author": "路遥", "work": "平凡的世界", "beat": "双水村夜话"},
        {"author": "路遥", "work": "平凡的世界", "beat": "润叶劝说"},
    ),
    "plot_progress": (
        {"author": "鲁迅", "work": "药", "beat": "交钱交货"},
        {"author": "鲁迅", "work": "阿Q正传", "beat": "造反了"},
        {"author": "鲁迅", "work": "故乡", "beat": "宏儿水生"},
        {"author": "鲁迅", "work": "祝福", "beat": "卫老婆子荐工"},
    ),
    "climax_beat": (
        {"author": "鲁迅", "work": "祝福", "beat": "你放着罢"},
        {"author": "鲁迅", "work": "孔乙己", "beat": "用手走来"},
        {"author": "鲁迅", "work": "药", "beat": "乌鸦飞去"},
        {"author": "鲁迅", "work": "故乡", "beat": "厚障壁"},
    ),
    "battle_action": (
        {"author": "鲁迅", "work": "铸剑", "beat": "鼎中死战"},
        {"author": "鲁迅", "work": "铸剑", "beat": "青剑劈落"},
        {"author": "鲁迅", "work": "奔月", "beat": "拉满弓"},
        {"author": "鲁迅", "work": "铸剑", "beat": "啮王鼻"},
    ),
    "mixed": (
        {"author": "鲁迅", "work": "故乡", "beat": "老爷"},
        {"author": "鲁迅", "work": "祝福", "beat": "年底气象"},
        {"author": "鲁迅", "work": "孔乙己", "beat": "温酒的人"},
        {"author": "郁达夫", "work": "春风沉醉的晚上", "beat": "陈二妹进来"},
        {"author": "老舍", "work": "骆驼祥子", "beat": "买车那天"},
        {"author": "路遥", "work": "平凡的世界", "beat": "黄土暮色"},
    ),
}

# web_serial 节奏库：只用 train split 作品，偏情节台阶/动作/劳动欲望，不含孔乙己/故乡质地核。
EXEMPLAR_CATALOG_WEB_SERIAL: dict[str, tuple[dict[str, str], ...]] = {
    "worldview_texture": (
        {"author": "鲁迅", "work": "药", "beat": "丁字街头"},
        {"author": "老舍", "work": "骆驼祥子", "beat": "买车那天"},
        {"author": "鲁迅", "work": "铸剑", "beat": "鼎水沸涌"},
        {"author": "鲁迅", "work": "故乡", "beat": "忙月"},
    ),
    "dialogue_dyad": (
        {"author": "老舍", "work": "骆驼祥子", "beat": "虎妞拉话"},
        {"author": "老舍", "work": "骆驼祥子", "beat": "刘四爷问车"},
        {"author": "老舍", "work": "茶馆", "beat": "王利发招呼"},
        {"author": "鲁迅", "work": "药", "beat": "交钱交货"},
    ),
    "plot_progress": (
        {"author": "鲁迅", "work": "药", "beat": "交钱交货"},
        {"author": "鲁迅", "work": "铸剑", "beat": "青剑劈落"},
        {"author": "老舍", "work": "骆驼祥子", "beat": "买车那天"},
        {"author": "鲁迅", "work": "故乡", "beat": "宏儿水生"},
    ),
    "climax_beat": (
        {"author": "鲁迅", "work": "药", "beat": "乌鸦飞去"},
        {"author": "鲁迅", "work": "铸剑", "beat": "啮王鼻"},
        {"author": "鲁迅", "work": "铸剑", "beat": "青剑劈落"},
        {"author": "鲁迅", "work": "铸剑", "beat": "鼎中死战"},
    ),
    "battle_action": (
        {"author": "鲁迅", "work": "铸剑", "beat": "鼎中死战"},
        {"author": "鲁迅", "work": "铸剑", "beat": "青剑劈落"},
        {"author": "鲁迅", "work": "铸剑", "beat": "啮王鼻"},
        {"author": "鲁迅", "work": "药", "beat": "抢灯笼"},
    ),
    "mixed": (
        {"author": "老舍", "work": "骆驼祥子", "beat": "买车那天"},
        {"author": "鲁迅", "work": "药", "beat": "交钱交货"},
        {"author": "鲁迅", "work": "铸剑", "beat": "鼎中死战"},
        {"author": "鲁迅", "work": "铸剑", "beat": "青剑劈落"},
        {"author": "老舍", "work": "茶馆", "beat": "王利发招呼"},
        {"author": "鲁迅", "work": "药", "beat": "乌鸦飞去"},
    ),
}

# Style-metric contract (exemplar_alignment). Independent of prefs SCHEMA_VERSION.
FEATURE_SCHEMA_ID = "sig.v1"
SIGNATURE_KEYS: tuple[str, ...] = (
    "quote_ratio",
    "mean_sent",
    "sent_cv",
    "scene_ratio",
    "meta_rate",
    "glue_rate",
    "short_quote_run",
    "short_unit_run",
    "hinge_norm",
    "para_mean",
    "battle_density",
    "world_density",
)
# Whitening needs a real cloud. Platform bank is 4/class — L1 until then.
WHITEN_MIN_N = 16
SCALE_FLOOR = 0.08
# L1-to-centroid floor for exemplar_alignment_high, scene_ratio_high, and
# dialogue_rhythm_varied (and not anti-pattern).
ALIGN_REWARD_FLOOR = 0.80
# fragment_mismatch only when declared class itself is a poor fit.
MISMATCH_ALIGN_FLOOR = 0.60

# Platform defaults — normalized per fragment row (literary / 经典文学向).
_PLATFORM_WEIGHTS: dict[str, dict[str, float]] = {
    "plot_progress": {
        "structure": 0.25,
        "character": 0.20,
        "pacing": 0.20,
        "voice": 0.15,
        "exemplar_alignment": 0.20,
    },
    "worldview_texture": {
        "structure": 0.15,
        "character": 0.10,
        "pacing": 0.15,
        "voice": 0.20,
        "exemplar_alignment": 0.40,
    },
    "climax_beat": {
        "structure": 0.20,
        "character": 0.25,
        "pacing": 0.25,
        "voice": 0.10,
        "exemplar_alignment": 0.20,
    },
    "battle_action": {
        "structure": 0.15,
        "character": 0.15,
        "pacing": 0.30,
        "voice": 0.10,
        "exemplar_alignment": 0.30,
    },
    "dialogue_dyad": {
        # Fitted 2026-08-25 from platform bank + 祥子/茶馆/平凡的世界 dialogue.
        "structure": 0.16,
        "character": 0.21,
        "pacing": 0.17,
        "voice": 0.16,
        "exemplar_alignment": 0.30,
    },
    "mixed": {
        # Fitted 2026-08-25 after adding 祥子/平凡的世界 mixed beats.
        "structure": 0.16,
        "character": 0.22,
        "pacing": 0.17,
        "voice": 0.16,
        "exemplar_alignment": 0.30,
    },
}

# web_serial — 人物仍中心，但情节/节奏/钩子权重更高；voice/范本对齐略降。
_PLATFORM_WEIGHTS_WEB: dict[str, dict[str, float]] = {
    "plot_progress": {
        "structure": 0.28,
        "character": 0.22,
        "pacing": 0.26,
        "voice": 0.08,
        "exemplar_alignment": 0.16,
    },
    "worldview_texture": {
        "structure": 0.18,
        "character": 0.14,
        "pacing": 0.18,
        "voice": 0.12,
        "exemplar_alignment": 0.38,
    },
    "climax_beat": {
        "structure": 0.22,
        "character": 0.20,
        "pacing": 0.28,
        "voice": 0.06,
        "exemplar_alignment": 0.24,
    },
    "battle_action": {
        "structure": 0.14,
        "character": 0.14,
        "pacing": 0.34,
        "voice": 0.06,
        "exemplar_alignment": 0.32,
    },
    "dialogue_dyad": {
        "structure": 0.18,
        "character": 0.28,
        "pacing": 0.20,
        "voice": 0.10,
        "exemplar_alignment": 0.24,
    },
    "mixed": {
        "structure": 0.24,
        "character": 0.24,
        "pacing": 0.22,
        "voice": 0.10,
        "exemplar_alignment": 0.20,
    },
}

_PLATFORM_WEIGHTS_BY_MODE: dict[str, dict[str, dict[str, float]]] = {
    "literary": _PLATFORM_WEIGHTS,
    "web_serial": _PLATFORM_WEIGHTS_WEB,
}

PLATFORM_SIGNAL_PENALTIES: dict[str, float] = {
    "hinge_dense": -0.12,
    "staccato_uniform": -0.18,
    "opening_institution": -0.10,
    "lore_dump": -0.10,
    "length_short": -0.08,
    "meta_knowing_high": -0.06,
    "glue_heavy": -0.05,
    "fragment_mismatch": -0.10,
    "serial_hook_flat": 0.0,
}

PLATFORM_SIGNAL_PENALTIES_WEB: dict[str, float] = {
    **PLATFORM_SIGNAL_PENALTIES,
    "staccato_uniform": -0.06,
    "hinge_dense": -0.06,
    "opening_institution": 0.0,
    "lore_dump": -0.12,
    "serial_hook_flat": -0.08,
}

PLATFORM_SIGNAL_PENALTIES_BY_MODE: dict[str, dict[str, float]] = {
    "literary": PLATFORM_SIGNAL_PENALTIES,
    "web_serial": PLATFORM_SIGNAL_PENALTIES_WEB,
}

PLATFORM_SIGNAL_REWARDS: dict[str, float] = {
    "scene_ratio_high": 0.08,
    "dialogue_rhythm_varied": 0.10,
    "exemplar_alignment_high": 0.12,
    "outline_duty_match": 0.10,
    "character_card_action": 0.08,
    "plot_step_visible": 0.0,
}

PLATFORM_SIGNAL_REWARDS_WEB: dict[str, float] = {
    **PLATFORM_SIGNAL_REWARDS,
    "plot_step_visible": 0.10,
}

PLATFORM_SIGNAL_REWARDS_BY_MODE: dict[str, dict[str, float]] = {
    "literary": PLATFORM_SIGNAL_REWARDS,
    "web_serial": PLATFORM_SIGNAL_REWARDS_WEB,
}

# Per-fragment signal strength defaults — never all 1.0; mode emphasizes different axes.
DEFAULT_STYLE_GAINS: dict[str, dict[str, float]] = {
    "literary": {
        "dialogue_dyad": 0.85,
        "worldview_texture": 0.80,
        "mixed": 0.70,
        "plot_progress": 0.55,
        "climax_beat": 0.50,
        "battle_action": 0.35,
    },
    "web_serial": {
        "plot_progress": 0.85,
        "climax_beat": 0.75,
        "battle_action": 0.70,
        "mixed": 0.70,
        "worldview_texture": 0.55,
        "dialogue_dyad": 0.50,
    },
}


def _signal_table(template: dict[str, float]) -> dict[str, dict[str, float]]:
    return {frag: dict(template) for frag in FRAGMENT_TYPES}


def _clamp_gain(raw: Any, default: float = 1.0) -> float:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        val = default
    return max(0.0, min(1.0, val))


def default_style_gains(work_mode: str = DEFAULT_WORK_MODE) -> dict[str, float]:
    mode = normalize_work_mode(work_mode)
    row = DEFAULT_STYLE_GAINS.get(mode) or DEFAULT_STYLE_GAINS[DEFAULT_WORK_MODE]
    return {frag: _clamp_gain(row.get(frag), 0.7) for frag in FRAGMENT_TYPES}


def apply_style_gains(
    gains: dict[str, Any] | None,
    *,
    work_mode: str = DEFAULT_WORK_MODE,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """Scale platform penalty/reward rows by per-fragment gain in [0, 1]."""
    mode = normalize_work_mode(work_mode)
    pen_tpl = PLATFORM_SIGNAL_PENALTIES_BY_MODE[mode]
    rew_tpl = PLATFORM_SIGNAL_REWARDS_BY_MODE[mode]
    defaults = default_style_gains(mode)
    penalties: dict[str, dict[str, float]] = {}
    rewards: dict[str, dict[str, float]] = {}
    for frag in FRAGMENT_TYPES:
        gain = _clamp_gain(
            (gains or {}).get(frag) if gains is not None else defaults.get(frag),
            defaults.get(frag, 0.7),
        )
        penalties[frag] = {
            key: round(float(val) * gain, 4) for key, val in pen_tpl.items()
        }
        rewards[frag] = {
            key: round(float(val) * gain, 4) for key, val in rew_tpl.items()
        }
    return penalties, rewards


def infer_style_gains(
    penalties: dict[str, Any] | None,
    rewards: dict[str, Any] | None,
    *,
    work_mode: str = DEFAULT_WORK_MODE,
) -> dict[str, float]:
    """Recover slider position from stored signal tables (mean |stored|/|platform|)."""
    mode = normalize_work_mode(work_mode)
    pen_tpl = PLATFORM_SIGNAL_PENALTIES_BY_MODE[mode]
    rew_tpl = PLATFORM_SIGNAL_REWARDS_BY_MODE[mode]
    out: dict[str, float] = {}
    for frag in FRAGMENT_TYPES:
        ratios: list[float] = []
        for key, plat in pen_tpl.items():
            if abs(plat) < 1e-9:
                continue
            ratios.append(abs(signal_coeff(penalties or {}, frag, key) / plat))
        for key, plat in rew_tpl.items():
            if abs(plat) < 1e-9:
                continue
            ratios.append(abs(signal_coeff(rewards or {}, frag, key) / plat))
        if not ratios:
            out[frag] = 0.0
        else:
            out[frag] = round(min(1.0, sum(ratios) / len(ratios)), 4)
    return out


def apply_style_leans(leans: list[str] | tuple[str, ...] | None) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """Build signal tables. Unlisted fragments are all-zero (style not leaned toward)."""
    wanted = {frag for frag in (leans or FRAGMENT_TYPES) if frag in FRAGMENT_TYPES}
    if not wanted:
        wanted = set(FRAGMENT_TYPES)
    gains = {frag: 1.0 if frag in wanted else 0.0 for frag in FRAGMENT_TYPES}
    return apply_style_gains(gains)


def fragment_style_on(
    penalties: dict[str, Any],
    rewards: dict[str, Any],
    fragment: str,
) -> bool:
    for table in (penalties, rewards):
        row = table.get(fragment) if isinstance(table, dict) else None
        if not isinstance(row, dict):
            continue
        if any(abs(float(v or 0)) > 0.001 for v in row.values()):
            return True
    return False


def flatten_fragment_signals(table: Any, fragment: str) -> dict[str, float]:
    """Tool/rubric payload: one fragment's coefficients as a flat map."""
    if not isinstance(table, dict):
        return {}
    row = table.get(fragment)
    if isinstance(row, dict):
        out: dict[str, float] = {}
        for k, v in row.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        return out
    out = {}
    for k, v in table.items():
        if isinstance(v, dict):
            continue
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def signal_coeff(table: Any, fragment: str, key: str) -> float:
    """Look up a penalty/reward coefficient (nested per fragment, or legacy flat)."""
    if not isinstance(table, dict):
        return 0.0
    row = table.get(fragment)
    if isinstance(row, dict):
        try:
            return float(row.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(table.get(key, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def validate_signal_map(raw: dict[str, Any], *, field: str, limit: float = 0.5) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in raw.items():
        key = str(k).strip()
        if not key:
            continue
        try:
            val = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{field}.{key}: invalid number") from None
        if abs(val) > limit:
            raise ValueError(f"{field}.{key}: abs value must be <= {limit}")
        out[key] = round(val, 4)
    return out


def coerce_signal_table(
    raw: Any,
    *,
    template: dict[str, float],
    field: str,
) -> dict[str, dict[str, float]]:
    base = _signal_table(template)
    if not isinstance(raw, dict) or not raw:
        return base
    first = next(iter(raw.values()), None)
    if isinstance(first, dict):
        for frag in FRAGMENT_TYPES:
            row = raw.get(frag)
            if not isinstance(row, dict):
                continue
            merged = dict(base[frag])
            for k, v in row.items():
                try:
                    merged[str(k)] = float(v)
                except (TypeError, ValueError):
                    continue
            base[frag] = merged
        return base
    flat = validate_signal_map(raw, field=field)
    return {frag: {**base[frag], **flat} for frag in FRAGMENT_TYPES}


def normalize_row(raw: dict[str, Any]) -> dict[str, float]:
    row: dict[str, float] = {}
    for key in DIMENSIONS:
        try:
            row[key] = max(0.0, float(raw.get(key, 0.0)))
        except (TypeError, ValueError):
            row[key] = 0.0
    total = sum(row.values())
    if total <= 0:
        return {k: 1.0 / len(DIMENSIONS) for k in DIMENSIONS}
    return {k: round(v / total, 4) for k, v in row.items()}


def normalize_work_mode(value: str | None) -> str:
    mode = (value or DEFAULT_WORK_MODE).strip().lower()
    if mode not in WORK_MODES:
        return DEFAULT_WORK_MODE
    return mode


def platform_fragment_weights(work_mode: str = DEFAULT_WORK_MODE) -> dict[str, dict[str, float]]:
    mode = normalize_work_mode(work_mode)
    table = _PLATFORM_WEIGHTS_BY_MODE[mode]
    return {f: normalize_row(table[f]) for f in FRAGMENT_TYPES}


def exemplar_catalog(work_mode: str = DEFAULT_WORK_MODE) -> dict[str, tuple[dict[str, str], ...]]:
    if normalize_work_mode(work_mode) == "web_serial":
        return EXEMPLAR_CATALOG_WEB_SERIAL
    return EXEMPLAR_CATALOG


def platform_prefs_payload(
    *,
    preset_label: str = "balanced",
    work_mode: str = DEFAULT_WORK_MODE,
    style_gains: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode = normalize_work_mode(work_mode)
    gains = style_gains if style_gains is not None else default_style_gains(mode)
    penalties, rewards = apply_style_gains(gains, work_mode=mode)
    return {
        "preset_label": preset_label if preset_label in PRESET_LABELS else "balanced",
        "work_mode": mode,
        "style_gains": {frag: _clamp_gain(gains.get(frag), default_style_gains(mode)[frag]) for frag in FRAGMENT_TYPES},
        "fragment_weights": platform_fragment_weights(mode),
        "signal_penalties": penalties,
        "signal_rewards": rewards,
        "schema_version": SCHEMA_VERSION,
        "exemplars": {k: [dict(x) for x in v] for k, v in exemplar_catalog(mode).items()},
    }


def apply_work_mode_overlay(prefs: dict[str, Any], work_mode: str) -> dict[str, Any]:
    """Account prefs 之上叠 work_mode：换维度权重与模式化 signal 模板。

    Account 只保留「哪些 fragment 开了 style lean」（整行置零），
    不保留上一 mode 的系数数值，避免 literary→web 时 web 专有键仍为 0。
    """
    mode = normalize_work_mode(work_mode)
    base = platform_prefs_payload(
        preset_label=str(prefs.get("preset_label") or "balanced"),
        work_mode=mode,
    )
    out = dict(prefs)
    out.update(base)
    old_pen = prefs.get("signal_penalties") if isinstance(prefs.get("signal_penalties"), dict) else {}
    old_rew = prefs.get("signal_rewards") if isinstance(prefs.get("signal_rewards"), dict) else {}
    for frag in FRAGMENT_TYPES:
        if fragment_style_on(old_pen, old_rew, frag):
            continue
        out["signal_penalties"][frag] = {
            k: 0.0 for k in (out.get("signal_penalties") or {}).get(frag, {})
        }
        out["signal_rewards"][frag] = {
            k: 0.0 for k in (out.get("signal_rewards") or {}).get(frag, {})
        }
    return out


def merge_prefs(
    stored: dict[str, Any] | None,
    *,
    work_mode: str = DEFAULT_WORK_MODE,
) -> dict[str, Any]:
    base = platform_prefs_payload(preset_label="balanced", work_mode=work_mode)
    if not stored:
        return base
    preset = str(stored.get("preset_label") or "balanced")
    base["preset_label"] = preset if preset in PRESET_LABELS else "custom"
    mode = normalize_work_mode(work_mode)
    pen_tpl = PLATFORM_SIGNAL_PENALTIES_BY_MODE[mode]
    rew_tpl = PLATFORM_SIGNAL_REWARDS_BY_MODE[mode]
    # Dimension weights are platform-wide (Ops-tuned). Account prefs only lean styles
    # by zeroing per-fragment signal tables.
    sp = stored.get("signal_penalties")
    base["signal_penalties"] = coerce_signal_table(
        sp, template=pen_tpl, field="signal_penalties"
    )
    sr = stored.get("signal_rewards")
    base["signal_rewards"] = coerce_signal_table(
        sr, template=rew_tpl, field="signal_rewards"
    )
    try:
        base["schema_version"] = int(stored.get("schema_version") or SCHEMA_VERSION)
    except (TypeError, ValueError):
        base["schema_version"] = SCHEMA_VERSION
    return base


def validate_fragment_weights(raw: dict[str, Any]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for frag in FRAGMENT_TYPES:
        row = raw.get(frag)
        if not isinstance(row, dict):
            raise ValueError(f"missing fragment_weights.{frag}")
        normalized = normalize_row(row)
        if min(normalized.values()) < 0.05:
            raise ValueError(f"fragment_weights.{frag}: each dimension must be >= 5% after normalize")
        out[frag] = normalized
    return out


def validate_signal_table(raw: dict[str, Any], *, field: str, limit: float = 0.5) -> dict[str, dict[str, float]]:
    table = coerce_signal_table(
        raw,
        template=PLATFORM_SIGNAL_PENALTIES if field == "signal_penalties" else PLATFORM_SIGNAL_REWARDS,
        field=field,
    )
    for frag, row in table.items():
        for key, val in row.items():
            if abs(val) > limit:
                raise ValueError(f"{field}.{frag}.{key}: abs value must be <= {limit}")
    return table


def normalize_fragment(value: str | None) -> str:
    frag = (value or "mixed").strip().lower()
    if frag not in FRAGMENT_TYPES:
        return "mixed"
    return frag
