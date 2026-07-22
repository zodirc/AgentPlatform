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

type EndUserAuthValue = {
  user: EndUser | null;
  isLoading: boolean;
  /** True after explicit "切换账号" until next successful login. */
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

export function useEndUserAuth(): EndUserAuthValue {
  return useContext(EndUserAuthContext);
}
