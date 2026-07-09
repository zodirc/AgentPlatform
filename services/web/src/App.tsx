import { Link, Navigate, useLocation } from "react-router-dom";
import { Button } from "./components/ui/button";
import { SettingsPage } from "./settings/SettingsPage";
import { SCENARIO_META } from "./shared/workbench/scenarioMeta";
import type { ScenarioId } from "./shared/workbench/types";
import { pathWithSession } from "./shared/workbench/sessionUrl";
import { UnifiedWorkbench } from "./shared/workbench/UnifiedWorkbench";
import {
  useWorkbenchSession,
  WorkbenchSessionProvider,
} from "./shared/workbench/workbenchSession";
import { WorkbenchProvider } from "./shared/workbench/workbenchProvider";

const SCENARIO_PATHS = ["/writing", "/agent", "/interview"] as const;

function Nav() {
  const { pathname } = useLocation();
  const { sessionId, startNewSession } = useWorkbenchSession();

  const link = (to: string, label: string) => (
    <Link
      to={to}
      className={`rounded-lg px-3 py-1.5 text-sm ${
        pathname === to.split("?")[0]
          ? "bg-slate-800 text-white"
          : "text-slate-400 hover:text-white"
      }`}
    >
      {label}
    </Link>
  );

  const copySessionLink = async () => {
    if (!sessionId) return;
    const url = `${window.location.origin}${pathWithSession(pathname, sessionId)}`;
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      // ignore
    }
  };

  return (
    <nav className="flex flex-wrap items-center gap-2 border-b border-slate-800 bg-slate-950/80 px-6 py-3">
      <span className="mr-2 font-semibold">Agent Platform</span>
      <span className="mr-2 text-xs text-slate-600">模式</span>
      {SCENARIO_PATHS.map((path) => {
        const id = path.slice(1) as ScenarioId;
        return link(pathWithSession(path, sessionId), SCENARIO_META[id].navLabel);
      })}
      {link("/settings/model", "模型设置")}
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {sessionId ? (
          <>
            <span
              className="text-[10px] text-slate-600"
              title={sessionId}
            >
              session {sessionId.slice(0, 8)}
            </span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 border-slate-700 px-2 text-xs text-slate-300"
              onClick={() => void copySessionLink()}
            >
              复制链接
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 border-slate-700 px-2 text-xs text-slate-300"
              onClick={() => void startNewSession()}
            >
              新建会话
            </Button>
          </>
        ) : null}
      </div>
    </nav>
  );
}

function MainContent() {
  const { pathname, search } = useLocation();

  if (pathname.startsWith("/s/")) {
    const sessionId = pathname.slice(3);
    return <Navigate to={`/writing?session=${sessionId}${search}`} replace />;
  }

  if (pathname === "/settings/model") {
    return <SettingsPage />;
  }

  if (
    pathname === "/" ||
    SCENARIO_PATHS.includes(pathname as (typeof SCENARIO_PATHS)[number])
  ) {
    if (pathname === "/") {
      return <Navigate to={`/writing${search}`} replace />;
    }
    return <UnifiedWorkbench />;
  }

  if (pathname.startsWith("/writing/")) {
    return <Navigate to={`/writing${search}`} replace />;
  }

  return <Navigate to={`/writing${search}`} replace />;
}

function AppBody() {
  const { sessionId } = useWorkbenchSession();

  return (
    <WorkbenchProvider key={sessionId ?? "pending"}>
      <div className="min-h-screen">
        <Nav />
        <MainContent />
      </div>
    </WorkbenchProvider>
  );
}

export function App() {
  return (
    <WorkbenchSessionProvider>
      <AppBody />
    </WorkbenchSessionProvider>
  );
}
