/**
 * 工作台 React Context：四场景共享同一 useWorkbenchImpl 状态树。
 */
import { createContext, useContext, useEffect, type ReactNode } from "react";
import type { ScenarioId, WorkbenchState } from "./types";
import { useWorkbenchImpl } from "./useWorkbench";

const WorkbenchContext = createContext<WorkbenchState | null>(null);

/** 注入跨 writing/agent/intel/collab 的统一工作台状态。 */
export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const wb = useWorkbenchImpl();
  return (
    <WorkbenchContext.Provider value={wb}>{children}</WorkbenchContext.Provider>
  );
}

/**
 * 读取 WorkbenchProvider 提供的全局状态。
 * @returns WorkbenchState
 * @throws 未包裹 Provider 时抛错
 */
export function useWorkbench(): WorkbenchState {
  const ctx = useContext(WorkbenchContext);
  if (!ctx) {
    throw new Error("useWorkbench must be used within WorkbenchProvider");
  }
  return ctx;
}

/**
 * 路由场景页挂载时同步 activeScenarioId；仅影响下一回合 scenario_id 与 chrome，不重置对话。
 * @param scenarioId 当前 URL 对应场景
 */
export function useSyncActiveScenario(scenarioId: ScenarioId) {
  const { setActiveScenario } = useWorkbench();
  useEffect(() => {
    setActiveScenario(scenarioId);
  }, [scenarioId, setActiveScenario]);
}
