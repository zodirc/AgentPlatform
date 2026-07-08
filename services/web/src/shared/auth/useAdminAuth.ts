import { useCallback, useEffect, useState } from "react";
import {
  clearAdminAuth,
  hasAdminAuth,
  isAuthRequired,
  setAdminPassword,
  verifyAdminAuth,
} from "../api/client";

type AdminAuthState = {
  /** Whether the unlock banner should be shown. */
  needsUnlock: boolean;
  checking: boolean;
  unlockError: string | null;
  unlock: (password: string) => Promise<boolean>;
};

export function useAdminAuth(): AdminAuthState {
  const [needsUnlock, setNeedsUnlock] = useState(false);
  const [checking, setChecking] = useState(true);
  const [unlockError, setUnlockError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const required = await isAuthRequired();
      if (cancelled) return;
      if (!required) {
        setNeedsUnlock(false);
        setChecking(false);
        return;
      }
      if (!hasAdminAuth()) {
        setNeedsUnlock(true);
        setChecking(false);
        return;
      }
      // Already unlocked in a previous visit — hide banner immediately.
      setNeedsUnlock(false);
      setChecking(false);
      const ok = await verifyAdminAuth();
      if (cancelled) return;
      if (!ok) {
        clearAdminAuth();
        setNeedsUnlock(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const unlock = useCallback(async (password: string) => {
    setUnlockError(null);
    setAdminPassword(password);
    const ok = await verifyAdminAuth();
    if (!ok) {
      clearAdminAuth();
      setUnlockError("密码错误，请使用 .env 中的 ADMIN_PASSWORD（默认 admin）");
      setNeedsUnlock(true);
      return false;
    }
    setNeedsUnlock(false);
    return true;
  }, []);

  return { needsUnlock, checking, unlockError, unlock };
}
