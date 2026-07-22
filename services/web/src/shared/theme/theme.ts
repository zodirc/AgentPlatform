/** Named UI themes (docs: appearance only — no agent path). */

export const THEME_IDS = ["ink", "paper", "contrast"] as const;
export type ThemeId = (typeof THEME_IDS)[number];

/** Legacy global key (pre per-user isolation). */
export const THEME_STORAGE_KEY = "agent.ui.theme";

export const THEME_META: Record<
  ThemeId,
  { label: string; description: string }
> = {
  ink: {
    label: "墨色",
    description: "深色工作台，青绿强调（默认）",
  },
  paper: {
    label: "纸色",
    description: "浅色阅读面，适合长时间写作",
  },
  contrast: {
    label: "高对比",
    description: "近黑底 + 高亮强调，便于辨识",
  },
};

function themeKeyForUser(userId: string | null | undefined): string {
  if (userId) return `${THEME_STORAGE_KEY}:${userId}`;
  return THEME_STORAGE_KEY;
}

export function isThemeId(value: string | null | undefined): value is ThemeId {
  return THEME_IDS.includes(value as ThemeId);
}

export function readStoredTheme(userId?: string | null): ThemeId {
  try {
    if (userId) {
      const perUser = localStorage.getItem(themeKeyForUser(userId));
      if (isThemeId(perUser)) return perUser;
      // One-time migrate from legacy global key.
      const legacy = localStorage.getItem(THEME_STORAGE_KEY);
      if (isThemeId(legacy)) {
        localStorage.setItem(themeKeyForUser(userId), legacy);
        return legacy;
      }
    } else {
      const raw = localStorage.getItem(THEME_STORAGE_KEY);
      if (isThemeId(raw)) return raw;
    }
  } catch {
    // ignore
  }
  return "ink";
}

/**
 * Apply theme to <html data-theme>.
 * When userId is set, persist under that user; otherwise only update DOM
 * (used before login / while switching).
 */
export function applyTheme(
  theme: ThemeId,
  userId?: string | null,
  options?: { persist?: boolean },
): void {
  document.documentElement.dataset.theme = theme;
  const persist = options?.persist ?? true;
  if (!persist) return;
  try {
    localStorage.setItem(themeKeyForUser(userId), theme);
    if (userId) {
      // Keep global key in sync for early boot before auth resolves.
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    }
  } catch {
    // ignore
  }
}
