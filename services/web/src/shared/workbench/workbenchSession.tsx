/**
 * 后端 Session 生命周期：从 URL/localStorage 解析 sessionId，并提供新建/切换会话。
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  type ReactNode,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { createSession, getSession } from "../api/client";
import { useEndUserAuth } from "../auth/EndUserAuth";
import {
  pathWithSession,
  readStoredSessionId,
  sessionIdFromPathname,
  sessionIdFromSearch,
  writeStoredSessionId,
} from "./sessionUrl";

/** WorkbenchSessionContext 对外 API。 */
type WorkbenchSessionContextValue = {
  /** 当前活跃的后端 session UUID，未就绪时为 null。 */
  sessionId: string | null;
  isLoading: boolean;
  error: Error | null;
  /** 创建 writing 场景新会话并导航到带 ?session= 的 URL。 */
  startNewSession: () => Promise<string>;
  /** 切换到已有会话；在设置页会回到 /writing。 */
  openSession: (sessionId: string) => Promise<void>;
};

const WorkbenchSessionContext = createContext<WorkbenchSessionContextValue>({
  sessionId: null,
  isLoading: true,
  error: null,
  startNewSession: async () => "",
  openSession: async () => undefined,
});

/**
 * 按优先级解析 sessionId：URL ?session= / /s/:id → localStorage → 新建。
 * @param userId 当前登录用户，用于隔离 localStorage
 * @returns 校验通过或新建的 session id
 */
async function resolveSessionId(userId: string): Promise<string> {
  const fromUrl =
    sessionIdFromSearch(window.location.search) ??
    sessionIdFromPathname(window.location.pathname);
  const fromStorage = readStoredSessionId(userId);
  const candidate = fromUrl ?? fromStorage;

  if (candidate) {
    try {
      const session = await getSession(candidate);
      writeStoredSessionId(session.id, userId);
      return session.id;
    } catch {
      // stale or foreign session — create below
    }
  }

  const session = await createSession("writing");
  writeStoredSessionId(session.id, userId);
  return session.id;
}

/**
 * 提供全局 sessionId 并在缺失时写回 URL query。
 * 一个后端 Session 对应整站共享对话，与场景路由正交。
 */
export function WorkbenchSessionProvider({ children }: { children: ReactNode }) {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user } = useEndUserAuth();

  const query = useQuery({
    queryKey: ["session", "shared", user?.id ?? "anon"],
    queryFn: () => resolveSessionId(user!.id),
    enabled: Boolean(user),
    staleTime: Number.POSITIVE_INFINITY,
    retry: 2,
  });

  const sessionId = query.data ?? null;

  useEffect(() => {
    if (!sessionId) return;
    if (pathname.startsWith("/s/")) {
      navigate(pathWithSession("/writing", sessionId), { replace: true });
      return;
    }
    const inUrl = sessionIdFromSearch(search);
    if (inUrl === sessionId) return;
    navigate(pathWithSession(pathname, sessionId), { replace: true });
  }, [sessionId, pathname, search, navigate]);

  const startNewSession = useCallback(async () => {
    if (!user) return "";
    const session = await createSession("writing");
    writeStoredSessionId(session.id, user.id);
    queryClient.setQueryData(["session", "shared", user.id], session.id);
    navigate(pathWithSession(pathname, session.id), { replace: true });
    return session.id;
  }, [navigate, pathname, queryClient, user]);

  const openSession = useCallback(
    async (nextId: string) => {
      if (!user) return;
      const session = await getSession(nextId);
      writeStoredSessionId(session.id, user.id);
      queryClient.setQueryData(["session", "shared", user.id], session.id);
      const settingsPath =
        pathname === "/settings" || pathname.startsWith("/settings/");
      navigate(
        pathWithSession(settingsPath ? "/writing" : pathname, session.id),
        { replace: true },
      );
    },
    [navigate, pathname, queryClient, user],
  );

  return (
    <WorkbenchSessionContext.Provider
      value={{
        sessionId,
        isLoading: Boolean(user) && query.isLoading,
        error: query.error as Error | null,
        startNewSession,
        openSession,
      }}
    >
      {children}
    </WorkbenchSessionContext.Provider>
  );
}

/**
 * 读取 WorkbenchSessionProvider 的 session 上下文。
 * @returns sessionId、加载态与 startNewSession/openSession
 */
export function useWorkbenchSession(): WorkbenchSessionContextValue {
  return useContext(WorkbenchSessionContext);
}
