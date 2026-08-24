/**
 * 终端用户认证上下文：cookie 会话、登录/注册/登出与切换账号。
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import {
  fetchMe,
  loginUser,
  logoutUser,
  registerUser,
  type EndUser,
} from "../api/client";
import { rememberUsername } from "./recentAccounts";
import { applyTheme, readStoredTheme } from "../theme/theme";
import { clearStoredSessionId } from "../workbench/sessionUrl";

/** EndUserAuthContext 对外形状。 */
type EndUserAuthValue = {
  user: EndUser | null;
  isLoading: boolean;
  /** 用户点击「切换账号」后为 true，直至下次登录成功。 */
  switchingAccount: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  switchAccount: () => Promise<void>;
};

const EndUserAuthContext = createContext<EndUserAuthValue>({
  user: null,
  isLoading: true,
  switchingAccount: false,
  login: async () => undefined,
  register: async () => undefined,
  logout: async () => undefined,
  switchAccount: async () => undefined,
});

/** 包裹应用树，维护 /auth/me 查询与登录态 mutation。 */
export function EndUserAuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [switchingAccount, setSwitchingAccount] = useState(false);
  const me = useQuery({
    queryKey: ["auth", "me"],
    queryFn: fetchMe,
    staleTime: 60_000,
    retry: false,
  });

  const afterAuth = useCallback(
    (user: EndUser) => {
      rememberUsername(user.username);
      applyTheme(readStoredTheme(user.id), user.id);
      queryClient.setQueryData(["auth", "me"], user);
      setSwitchingAccount(false);
    },
    [queryClient],
  );

  const login = useCallback(
    async (username: string, password: string) => {
      const user = await loginUser(username, password);
      afterAuth(user);
    },
    [afterAuth],
  );

  const register = useCallback(
    async (username: string, password: string) => {
      const user = await registerUser(username, password);
      afterAuth(user);
    },
    [afterAuth],
  );

  const clearSessionCaches = useCallback(
    (userId: string | null | undefined) => {
      clearStoredSessionId(userId);
      queryClient.setQueryData(["auth", "me"], null);
      queryClient.removeQueries({ queryKey: ["session"] });
      queryClient.removeQueries({ queryKey: ["sessions"] });
      queryClient.removeQueries({ queryKey: ["works"] });
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    const userId = me.data?.id ?? null;
    await logoutUser();
    clearSessionCaches(userId);
    setSwitchingAccount(false);
  }, [clearSessionCaches, me.data?.id]);

  const switchAccount = useCallback(async () => {
    const userId = me.data?.id ?? null;
    await logoutUser();
    clearSessionCaches(userId);
    setSwitchingAccount(true);
  }, [clearSessionCaches, me.data?.id]);

  return (
    <EndUserAuthContext.Provider
      value={{
        user: me.data ?? null,
        isLoading: me.isLoading,
        switchingAccount,
        login,
        register,
        logout,
        switchAccount,
      }}
    >
      {children}
    </EndUserAuthContext.Provider>
  );
}

/**
 * 读取当前终端用户与认证操作。
 * @returns user、isLoading、login/register/logout/switchAccount
 */
export function useEndUserAuth(): EndUserAuthValue {
  return useContext(EndUserAuthContext);
}
