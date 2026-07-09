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
import {
  pathWithSession,
  readStoredSessionId,
  sessionIdFromPathname,
  sessionIdFromSearch,
  writeStoredSessionId,
} from "./sessionUrl";

type WorkbenchSessionContextValue = {
  sessionId: string | null;
  isLoading: boolean;
  error: Error | null;
  startNewSession: () => Promise<string>;
};

const WorkbenchSessionContext = createContext<WorkbenchSessionContextValue>({
  sessionId: null,
  isLoading: true,
  error: null,
  startNewSession: async () => "",
});

async function resolveSessionId(): Promise<string> {
  const fromUrl =
    sessionIdFromSearch(window.location.search) ??
    sessionIdFromPathname(window.location.pathname);
  const fromStorage = readStoredSessionId();
  const candidate = fromUrl ?? fromStorage;

  if (candidate) {
    try {
      const session = await getSession(candidate);
      writeStoredSessionId(session.id);
      return session.id;
    } catch {
      // stale id — create a fresh session below
    }
  }

  const session = await createSession("writing");
  writeStoredSessionId(session.id);
  return session.id;
}

/** One backend Session; id comes from URL (?session=) or localStorage. */
export function WorkbenchSessionProvider({ children }: { children: ReactNode }) {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["session", "shared"],
    queryFn: resolveSessionId,
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
    const session = await createSession("writing");
    writeStoredSessionId(session.id);
    queryClient.setQueryData(["session", "shared"], session.id);
    navigate(pathWithSession(pathname, session.id), { replace: true });
    return session.id;
  }, [navigate, pathname, queryClient]);

  return (
    <WorkbenchSessionContext.Provider
      value={{
        sessionId,
        isLoading: query.isLoading,
        error: query.error as Error | null,
        startNewSession,
      }}
    >
      {children}
    </WorkbenchSessionContext.Provider>
  );
}

export function useWorkbenchSession(): WorkbenchSessionContextValue {
  return useContext(WorkbenchSessionContext);
}
