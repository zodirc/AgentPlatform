import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { InterviewWorkbench } from "./scenarios/interview/InterviewWorkbench";
import { AgentWorkbench } from "./scenarios/agent/AgentWorkbench";
import { WritingWorkbench } from "./scenarios/writing/WritingWorkbench";
import { SettingsPage } from "./settings/SettingsPage";

function Nav() {
  const { pathname } = useLocation();
  const link = (to: string, label: string) => (
    <Link
      to={to}
      className={`rounded-lg px-3 py-1.5 text-sm ${
        pathname === to ? "bg-slate-800 text-white" : "text-slate-400 hover:text-white"
      }`}
    >
      {label}
    </Link>
  );

  return (
    <nav className="flex items-center gap-2 border-b border-slate-800 bg-slate-950/80 px-6 py-3">
      <span className="mr-4 font-semibold">Agent Platform</span>
      {link("/writing", "写作")}
      {link("/agent", "Agent")}
      {link("/interview", "访谈")}
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
        <Route path="/writing" element={<WritingWorkbench />} />
        <Route path="/agent" element={<AgentWorkbench />} />
        <Route path="/interview" element={<InterviewWorkbench />} />
        <Route path="/settings/model" element={<SettingsPage />} />
      </Routes>
    </div>
  );
}
