import { Navigate, useLocation } from "react-router-dom";
import { ScenarioWorkbenchView } from "./ScenarioWorkbench";
import { scenarioFromPathname } from "./scenarioRoutes";
import type { ScenarioId } from "./types";
import { useSyncActiveScenario, useWorkbench } from "./workbenchProvider";
import { useWorkbenchSession } from "./workbenchSession";

export function UnifiedWorkbench() {
  const { pathname } = useLocation();
  const parsed = scenarioFromPathname(pathname);
  const scenarioId: ScenarioId = parsed ?? "writing";
  const { sessionId, isLoading, error } = useWorkbenchSession();
  const wb = useWorkbench();
  useSyncActiveScenario(scenarioId);

  if (!parsed) {
    return <Navigate to="/writing" replace />;
  }

  if (isLoading && !sessionId) {
    return (
      <div className="flex h-[calc(100vh-49px)] items-center justify-center text-sm text-muted-foreground">
        正在连接会话…
      </div>
    );
  }

  if (error && !sessionId) {
    const message = error instanceof Error ? error.message : String(error);
    return (
      <div className="flex h-[calc(100vh-49px)] items-center justify-center text-sm text-destructive">
        无法创建会话：{message}
      </div>
    );
  }

  return <ScenarioWorkbenchView scenarioId={scenarioId} wb={wb} />;
}
