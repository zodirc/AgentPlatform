import { Link, Navigate, useLocation } from "react-router-dom";
import { SettingsPage } from "./settings/SettingsPage";
import { SCENARIO_META } from "./shared/workbench/scenarioMeta";
import type { ScenarioId } from "./shared/workbench/types";
import { UnifiedWorkbench } from "./shared/workbench/UnifiedWorkbench";
import {
  useWorkbenchSession,
  WorkbenchSessionProvider,
} from "./shared/workbench/workbenchSession";
import { WorkbenchProvider } from "./shared/workbench/workbenchProvider";

const SCENARIO_PATHS = ["/writing", "/agent", "/interview"] as const;

function Nav() {
  const { pathname } = useLocation();
  const { sessionId } = useWorkbenchSession();

  const link = (to: string, label: string) => (
    <Link
      to={to}
      className={`rounded-lg px-3 py-1.5 text-sm ${
        pathname === to
          ? "bg-slate-800 text-white"
          : "text-slate-400 hover:text-white"
      }`}
    >
      {label}
    </Link>
  );

  return (
    <nav className="flex flex-wrap items-center gap-2 border-b border-slate-800 bg-slate-950/80 px-6 py-3">
      <span className="mr-2 font-semibold">Agent Platform</span>
      <span className="mr-2 text-xs text-slate-600">模式</span>
      {SCENARIO_PATHS.map((path) => {
        const id = path.slice(1) as ScenarioId;
        return link(path, SCENARIO_META[id].navLabel);
      })}
      {link("/settings/model", "模型设置")}
      {sessionId ? (
        <span
          className="ml-auto text-[10px] text-slate-600"
          title="写作 / Agent / 访谈共用同一会话与同一条对话"
        >
          session {sessionId.slice(0, 8)}
        </span>
      ) : null}
    </nav>
  );
}

function MainContent() {
  const { pathname } = useLocation();

  if (pathname === "/settings/model") {
    return <SettingsPage />;
  }

  if (pathname === "/" || SCENARIO_PATHS.includes(pathname as (typeof SCENARIO_PATHS)[number])) {
    if (pathname === "/") {
      return <Navigate to="/writing" replace />;
    }
    return <UnifiedWorkbench />;
  }

  if (pathname.startsWith("/writing/")) {
    return <Navigate to="/writing" replace />;
  }

  return <Navigate to="/writing" replace />;
}

export function App() {
  return (
    <WorkbenchSessionProvider>
      <WorkbenchProvider>
        <div className="min-h-screen">
          <Nav />
          <MainContent />
        </div>
      </WorkbenchProvider>
    </WorkbenchSessionProvider>
  );
}
