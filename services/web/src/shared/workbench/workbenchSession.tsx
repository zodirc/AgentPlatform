import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";
import { createSession } from "../api/client";

type WorkbenchSessionContextValue = {
  sessionId: string | null;
  isLoading: boolean;
  error: Error | null;
};

const WorkbenchSessionContext = createContext<WorkbenchSessionContextValue>({
  sessionId: null,
  isLoading: true,
  error: null,
});

/** One backend Session shared across writing / agent / interview (Cursor-style). */
export function WorkbenchSessionProvider({ children }: { children: ReactNode }) {
  const query = useQuery({
    queryKey: ["session", "shared"],
    queryFn: () => createSession("writing"),
    staleTime: Number.POSITIVE_INFINITY,
    retry: 2,
  });

  return (
    <WorkbenchSessionContext.Provider
      value={{
        sessionId: query.data?.id ?? null,
        isLoading: query.isLoading,
        error: query.error as Error | null,
      }}
    >
      {children}
    </WorkbenchSessionContext.Provider>
  );
}

export function useWorkbenchSession(): WorkbenchSessionContextValue {
  return useContext(WorkbenchSessionContext);
}
