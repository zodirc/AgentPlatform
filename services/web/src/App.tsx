import { useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { Button } from "./components/ui/button";
import { SettingsPage } from "./settings/SettingsPage";
import { EndUserAuthProvider, useEndUserAuth } from "./shared/auth/EndUserAuth";
import { LoginPage } from "./shared/auth/LoginPage";
import { SCENARIO_META } from "./shared/workbench/scenarioMeta";
import type { ScenarioId } from "./shared/workbench/types";
import { pathWithSession } from "./shared/workbench/sessionUrl";
import { SessionHistoryDrawer } from "./shared/workbench/SessionHistoryDrawer";
import { UnifiedWorkbench } from "./shared/workbench/UnifiedWorkbench";
import {
  useWorkbenchSession,
  WorkbenchSessionProvider,
} from "./shared/workbench/workbenchSession";
import { WorkbenchProvider } from "./shared/workbench/workbenchProvider";

const SCENARIO_PATHS = ["/writing", "/agent", "/interview"] as const;

function Nav() {
  const { pathname } = useLocation();
  const { sessionId, startNewSession, openSession } = useWorkbenchSession();
  const { user, logout } = useEndUserAuth();
  const [historyOpen, setHistoryOpen] = useState(false);

  const link = (to: string, label: string) => (
    <Link
      to={to}
      className={`rounded-lg px-3 py-1.5 text-sm ${
        pathname === to.split("?")[0]
          ? "bg-muted text-foreground"
          : "text-muted-foreground hover:text-foreground"
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
    <>
      <nav className="flex flex-wrap items-center gap-2 border-b border-border bg-background/80 px-6 py-3">
        <span className="mr-2 font-semibold">Agent Platform</span>
        <span className="mr-2 text-xs text-muted-foreground/80">模式</span>
        {SCENARIO_PATHS.map((path) => {
          const id = path.slice(1) as ScenarioId;
          return link(pathWithSession(path, sessionId), SCENARIO_META[id].navLabel);
        })}
        {link("/settings/model", "设置")}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {user ? (
            <span className="text-[11px] text-muted-foreground" title={user.id}>
              {user.username}
            </span>
          ) : null}
          {sessionId ? (
            <>
              <span
                className="text-[10px] text-muted-foreground/80"
                title={sessionId}
              >
                session {sessionId.slice(0, 8)}
              </span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 border-input px-2 text-xs text-foreground/90"
                onClick={() => setHistoryOpen(true)}
              >
                历史
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 border-input px-2 text-xs text-foreground/90"
                onClick={() => void copySessionLink()}
              >
                复制链接
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 border-input px-2 text-xs text-foreground/90"
                onClick={() => void startNewSession()}
              >
                新建会话
              </Button>
            </>
          ) : null}
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 border-input px-2 text-xs text-foreground/90"
            onClick={() => void logout()}
          >
            退出
          </Button>
        </div>
      </nav>
      <SessionHistoryDrawer
        open={historyOpen}
        currentSessionId={sessionId}
        onClose={() => setHistoryOpen(false)}
        onSelect={(id) => {
          setHistoryOpen(false);
          void openSession(id);
        }}
        onDeletedCurrent={() => {
          setHistoryOpen(false);
          void startNewSession();
        }}
      />
    </>
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

function AuthenticatedApp() {
  const { user, isLoading } = useEndUserAuth();

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-sm text-muted-foreground">
        正在检查登录状态…
      </div>
    );
  }
  if (!user) {
    return <LoginPage />;
  }

  return (
    <WorkbenchSessionProvider>
      <AppBody />
    </WorkbenchSessionProvider>
  );
}

export function App() {
  return (
    <EndUserAuthProvider>
      <AuthenticatedApp />
    </EndUserAuthProvider>
  );
}
