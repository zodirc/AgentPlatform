/**
 * 管理端 HTTP Basic 解锁：检测 API 是否需要密码、验证与解锁横幅状态。
 */
import { useCallback, useEffect, useState } from "react";
import {
  clearAdminAuth,
  hasAdminAuth,
  isAuthRequired,
  setAdminPassword,
  verifyAdminAuth,
} from "../api/client";

/** useAdminAuth 返回值。 */
type AdminAuthState = {
  /** 是否应显示管理端解锁横幅。 */
  needsUnlock: boolean;
  checking: boolean;
  unlockError: string | null;
  /** 提交 ADMIN_PASSWORD 并验证，成功则隐藏横幅。 */
  unlock: (password: string) => Promise<boolean>;
};

/**
 * 挂载时探测 /admin 是否 401，并校验 sessionStorage 中的 Basic token。
 * @returns needsUnlock、checking、unlock 等
 */
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
