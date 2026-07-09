import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ScenarioWorkbench } from "./shared/workbench/ScenarioWorkbench";
import { SCENARIO_META } from "./shared/workbench/scenarioMeta";
import type { ScenarioId } from "./shared/workbench/types";
import { SettingsPage } from "./settings/SettingsPage";

const SCENARIO_ROUTES: { path: string; id: ScenarioId }[] = [
  { path: "/writing", id: "writing" },
  { path: "/agent", id: "agent" },
  { path: "/interview", id: "interview" },
];

function Nav() {
  const { pathname } = useLocation();
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
    <nav className="flex items-center gap-2 border-b border-slate-800 bg-slate-950/80 px-6 py-3">
      <span className="mr-2 font-semibold">Agent Platform</span>
      <span className="mr-2 text-xs text-slate-600">模式</span>
      {SCENARIO_ROUTES.map(({ path, id }) =>
        link(path, SCENARIO_META[id].navLabel),
      )}
      {link("/settings/model", "模型设置")}
    </nav>
  );
}

export function App() {
  return (
    <div className="min-h-screen">
      <Nav />
      <Routes>
        <Route path="/" element={<Navigate to="/writing" replace />} />
        {SCENARIO_ROUTES.map(({ path, id }) => (
          <Route
            key={id}
            path={path}
            element={<ScenarioWorkbench key={id} scenarioId={id} />}
          />
        ))}
        <Route path="/settings/model" element={<SettingsPage />} />
      </Routes>
    </div>
  );
}
