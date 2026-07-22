/** Named UI themes (docs: appearance only — no agent path). */

export const THEME_IDS = ["ink", "paper", "contrast"] as const;
export type ThemeId = (typeof THEME_IDS)[number];

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

export function isThemeId(value: string | null | undefined): value is ThemeId {
  return THEME_IDS.includes(value as ThemeId);
}

export function readStoredTheme(): ThemeId {
  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY);
    if (isThemeId(raw)) return raw;
  } catch {
    // ignore
  }
  return "ink";
}

/** Apply theme to <html data-theme> — CSS variables drive all surfaces. */
export function applyTheme(theme: ThemeId): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // ignore
  }
}
