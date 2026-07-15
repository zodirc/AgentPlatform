import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  type ReactNode,
} from "react";
import {
  fetchMe,
  loginUser,
  logoutUser,
  registerUser,
  type EndUser,
} from "../api/client";

type EndUserAuthValue = {
  user: EndUser | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const EndUserAuthContext = createContext<EndUserAuthValue>({
  user: null,
  isLoading: true,
  login: async () => undefined,
  register: async () => undefined,
  logout: async () => undefined,
});

export function EndUserAuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: ["auth", "me"],
    queryFn: fetchMe,
    staleTime: 60_000,
    retry: false,
  });

  const login = useCallback(
    async (username: string, password: string) => {
      const user = await loginUser(username, password);
      queryClient.setQueryData(["auth", "me"], user);
    },
    [queryClient],
  );

  const register = useCallback(
    async (username: string, password: string) => {
      const user = await registerUser(username, password);
      queryClient.setQueryData(["auth", "me"], user);
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    await logoutUser();
    queryClient.setQueryData(["auth", "me"], null);
    queryClient.removeQueries({ queryKey: ["session"] });
    queryClient.removeQueries({ queryKey: ["sessions"] });
  }, [queryClient]);

  return (
    <EndUserAuthContext.Provider
      value={{
        user: me.data ?? null,
        isLoading: me.isLoading,
        login,
        register,
        logout,
      }}
    >
      {children}
    </EndUserAuthContext.Provider>
  );
}

export function useEndUserAuth(): EndUserAuthValue {
  return useContext(EndUserAuthContext);
}
