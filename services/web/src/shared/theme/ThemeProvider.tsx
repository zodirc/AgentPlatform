import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useEndUserAuth } from "../auth/EndUserAuth";
import {
  applyTheme,
  readStoredTheme,
  type ThemeId,
  THEME_IDS,
  THEME_META,
} from "./theme";

type ThemeContextValue = {
  theme: ThemeId;
  setTheme: (theme: ThemeId) => void;
  themes: typeof THEME_IDS;
  meta: typeof THEME_META;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const { user } = useEndUserAuth();
  const userId = user?.id ?? null;
  const [theme, setThemeState] = useState<ThemeId>(() => readStoredTheme(null));

  useEffect(() => {
    if (!userId) return;
    const next = readStoredTheme(userId);
    setThemeState(next);
    applyTheme(next, userId);
  }, [userId]);

  const setTheme = useCallback(
    (next: ThemeId) => {
      setThemeState(next);
      applyTheme(next, userId);
    },
    [userId],
  );

  const value = useMemo(
    () => ({ theme, setTheme, themes: THEME_IDS, meta: THEME_META }),
    [theme, setTheme],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within ThemeProvider");
  }
  return ctx;
}
