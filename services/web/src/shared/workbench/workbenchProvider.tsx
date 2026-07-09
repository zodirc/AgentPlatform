import { createContext, useContext, useEffect, type ReactNode } from "react";
import type { ScenarioId, WorkbenchState } from "./types";
import { useWorkbenchImpl } from "./useWorkbench";

const WorkbenchContext = createContext<WorkbenchState | null>(null);

/** Single shared workbench state across writing / agent / interview (Cursor-style). */
export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const wb = useWorkbenchImpl();
  return (
    <WorkbenchContext.Provider value={wb}>{children}</WorkbenchContext.Provider>
  );
}

export function useWorkbench(): WorkbenchState {
  const ctx = useContext(WorkbenchContext);
  if (!ctx) {
    throw new Error("useWorkbench must be used within WorkbenchProvider");
  }
  return ctx;
}

/** URL mode only affects the next turn's scenario_id and chrome — not conversation state. */
export function useSyncActiveScenario(scenarioId: ScenarioId) {
  const { setActiveScenario } = useWorkbench();
  useEffect(() => {
    setActiveScenario(scenarioId);
  }, [scenarioId, setActiveScenario]);
}
