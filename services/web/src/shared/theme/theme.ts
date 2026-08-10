/** Named UI themes (docs: appearance only — no agent path). */

export const THEME_IDS = [
  "ink",
  "dusk",
  "ocean",
  "paper",
  "mist",
  "stone",
  "contrast",
] as const;
export type ThemeId = (typeof THEME_IDS)[number];

/** Legacy global key (pre per-user isolation). */
export const THEME_STORAGE_KEY = "agent.ui.theme";

export const THEME_META: Record<
  ThemeId,
  {
    label: string;
    description: string;
    /** Swatch pair for the switcher (bg / accent), CSS color. */
    swatch: { bg: string; accent: string };
    scheme: "dark" | "light";
  }
> = {
  ink: {
    label: "墨色",
    description: "柔和深色工作台，青绿点缀（默认）",
    swatch: { bg: "#1a1f2a", accent: "#3d9e8f" },
    scheme: "dark",
  },
  dusk: {
    label: "暮色",
    description: "低对比蓝灰深色，长时间盯屏更省眼",
    swatch: { bg: "#232833", accent: "#7a93b0" },
    scheme: "dark",
  },
  ocean: {
    label: "海色",
    description: "深夜海军蓝底，平静蓝强调",
    swatch: { bg: "#15202b", accent: "#5b8fb8" },
    scheme: "dark",
  },
  paper: {
    label: "纸色",
    description: "柔和浅色阅读面，适合写作",
    swatch: { bg: "#eef1f4", accent: "#2f7a6e" },
    scheme: "light",
  },
  mist: {
    label: "雾色",
    description: "灰蓝浅色，比纯白更不刺眼",
    swatch: { bg: "#e6ebf0", accent: "#5a738c" },
    scheme: "light",
  },
  stone: {
    label: "石色",
    description: "暖灰浅色阅读面，克制的石青强调",
    swatch: { bg: "#eceae6", accent: "#5c7368" },
    scheme: "light",
  },
  contrast: {
    label: "高对比",
    description: "深底 + 琥珀强调，需要强辨识时使用",
    swatch: { bg: "#121212", accent: "#d4a017" },
    scheme: "dark",
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
