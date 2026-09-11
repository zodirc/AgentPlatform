export type WorkModeChoice = "auto" | "literary" | "web_serial";
export type BookScopeChoice = "auto" | "short" | "single" | "long";
export type RegimeChoice = "auto" | "author" | "strict";

export type Gains = Record<string, number>;

export const STYLE_IDS = [
  "plot_progress",
  "worldview_texture",
  "climax_beat",
  "battle_action",
  "dialogue_dyad",
  "mixed",
] as const;

export const DEFAULT_GAINS: Record<
  Exclude<WorkModeChoice, "auto">,
  Record<string, number>
> = {
  literary: {
    dialogue_dyad: 0.85,
    worldview_texture: 0.8,
    mixed: 0.7,
    plot_progress: 0.55,
    climax_beat: 0.5,
    battle_action: 0.35,
  },
  web_serial: {
    plot_progress: 0.85,
    climax_beat: 0.75,
    battle_action: 0.7,
    mixed: 0.7,
    worldview_texture: 0.55,
    dialogue_dyad: 0.5,
  },
};

type StoredPrefs = {
  work_mode?: { source?: string; mode?: string };
  book_scope?: { source?: string; scope?: string };
  style_gains?: Record<string, number>;
  regime?: { value?: string; source?: string };
};

export function modeForDefaults(choice: WorkModeChoice): "literary" | "web_serial" {
  return choice === "web_serial" ? "web_serial" : "literary";
}

export function fullDefaults(choice: WorkModeChoice): Gains {
  return { ...DEFAULT_GAINS[modeForDefaults(choice)] };
}

export function parsePrefs(raw: string | undefined): {
  choice: WorkModeChoice;
  scope: BookScopeChoice;
  regime: RegimeChoice;
  gains: Gains;
  extra: Record<string, unknown>;
} {
  const fallbackChoice: WorkModeChoice = "auto";
  const fallbackScope: BookScopeChoice = "auto";
  const fallbackRegime: RegimeChoice = "auto";
  const fallbackGains = fullDefaults(fallbackChoice);
  if (!raw?.trim()) {
    return {
      choice: fallbackChoice,
      scope: fallbackScope,
      regime: fallbackRegime,
      gains: fallbackGains,
      extra: {},
    };
  }
  try {
    const data = JSON.parse(raw) as StoredPrefs & Record<string, unknown>;
    let choice: WorkModeChoice = "auto";
    if (
      data.work_mode?.source === "user" &&
      (data.work_mode.mode === "literary" || data.work_mode.mode === "web_serial")
    ) {
      choice = data.work_mode.mode;
    }
    let scope: BookScopeChoice = "auto";
    if (
      data.book_scope?.source === "user" &&
      (data.book_scope.scope === "short" ||
        data.book_scope.scope === "single" ||
        data.book_scope.scope === "long")
    ) {
      scope = data.book_scope.scope;
    }
    let regime: RegimeChoice = "auto";
    if (
      data.regime?.source === "user" &&
      (data.regime.value === "author" || data.regime.value === "strict")
    ) {
      regime = data.regime.value;
    }
    const base = fullDefaults(choice);
    const gains: Gains = { ...base };
    if (data.style_gains && typeof data.style_gains === "object") {
      for (const id of STYLE_IDS) {
        const v = Number(data.style_gains[id]);
        if (Number.isFinite(v)) gains[id] = Math.max(0, Math.min(1, v));
      }
    }
    const extra = { ...data };
    delete extra.work_mode;
    delete extra.book_scope;
    delete extra.style_gains;
    delete extra.regime;
    return { choice, scope, regime, gains, extra };
  } catch {
    return {
      choice: fallbackChoice,
      scope: fallbackScope,
      regime: fallbackRegime,
      gains: fallbackGains,
      extra: {},
    };
  }
}

export function serializePrefs(
  choice: WorkModeChoice,
  gains: Gains,
  scope: BookScopeChoice,
  regime: RegimeChoice,
  extra: Record<string, unknown> = {},
): string {
  const work_mode =
    choice === "auto"
      ? { source: "auto", mode: "literary" }
      : { source: "user", mode: choice };
  const book_scope =
    scope === "auto"
      ? { source: "auto", scope: "single" }
      : { source: "user", scope };
  const style_gains = Object.fromEntries(
    STYLE_IDS.map((id) => [id, Math.round((gains[id] ?? 0.7) * 100) / 100]),
  );
  const payload: Record<string, unknown> = {
    ...extra,
    work_mode,
    book_scope,
    style_gains,
  };
  if (regime === "auto") {
    payload.regime = { value: "author", source: "default" };
  } else {
    payload.regime = { value: regime, source: "user" };
  }
  return `${JSON.stringify(payload, null, 2)}\n`;
}
