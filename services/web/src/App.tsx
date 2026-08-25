/**
 * 应用根组件与路由分发。
 *
 * 路由概览：
 * - `/`、`/writing`、`/agent`、`/intel`、`/collab` — 统一工作台（UnifiedWorkbench），`/` 重定向到 `/writing`
 * - `/s/:sessionId` — 短链，重定向到 `/writing?session=…`
 * - `/settings`、`/settings/*` — 账户/模型/工作区设置
 * - `/ops/:workId/test` — Eval 控制台；`/history`、`/runs/:id` 子路由
 * - `/ops/:workId/retrieval|envelopes|raw|official|writing` — 各 Ops 审计/实验页（lazy + 独立 ErrorBoundary）
 * - 未匹配路径 — 回退到 `/writing`
 *
 * 认证：非 Ops 路径走 AuthenticatedApp（EndUserAuth → WorkbenchSession → WorkbenchProvider）。
 * Ops 路径与用户工作台隔离边界，避免单侧崩溃拖垮整站。
 */
import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { ListTree, History, Plus } from "lucide-react";
import { Button } from "./components/ui/button";
import { SettingsPage } from "./settings/SettingsPage";
import { ErrorBoundary } from "./shared/ErrorBoundary";
import { useEndUserAuth } from "./shared/auth/EndUserAuth";
import { LoginPage } from "./shared/auth/LoginPage";
import { pathWithSession } from "./shared/workbench/sessionUrl";
import {
  readSettingsReturn,
  rememberSettingsReturn,
} from "./shared/workbench/settingsReturn";
import { SessionHistoryDrawer } from "./shared/workbench/SessionHistoryDrawer";
import { UnifiedWorkbench } from "./shared/workbench/UnifiedWorkbench";
import {
  useWorkbenchSession,
  WorkbenchSessionProvider,
} from "./shared/workbench/workbenchSession";
import { WorkbenchProvider } from "./shared/workbench/workbenchProvider";
import {
  AgentPanelProvider,
  useAgentPanel,
} from "./shared/workbench/agentPanel";
import { SiteBrandMark } from "./shared/SiteBrandMark";
import { SITE_APP } from "./shared/siteBrand";
import { useSiteBrand } from "./shared/useSiteBrand";
import { scenarioMetaFromPath } from "./shared/workbench/scenarioMeta";
import { ThemeSwitcher } from "./shared/theme/ThemeSwitcher";

/** Ops pages stay out of the workbench first paint (route-level code split). */
const EvalConsolePage = lazy(() =>
  import("./ops/EvalConsolePage").then((m) => ({ default: m.EvalConsolePage })),
);
const EvalHistoryPage = lazy(() =>
  import("./ops/EvalHistoryPage").then((m) => ({ default: m.EvalHistoryPage })),
);
const EvalRunReportPage = lazy(() =>
  import("./ops/EvalRunReportPage").then((m) => ({
    default: m.EvalRunReportPage,
  })),
);
const EnvelopeAuditPage = lazy(() =>
  import("./ops/EnvelopeAuditPage").then((m) => ({
    default: m.EnvelopeAuditPage,
  })),
);
const RawAuditPage = lazy(() =>
  import("./ops/RawAuditPage").then((m) => ({ default: m.RawAuditPage })),
);
const RetrievalAuditPage = lazy(() =>
  import("./ops/RetrievalAuditPage").then((m) => ({
    default: m.RetrievalAuditPage,
  })),
);
const OfficialBenchPage = lazy(() =>
  import("./ops/OfficialBenchPage").then((m) => ({
    default: m.OfficialBenchPage,
  })),
);
const WritingSignalsLabPage = lazy(() =>
  import("./ops/WritingSignalsLabPage").then((m) => ({
    default: m.WritingSignalsLabPage,
  })),
);

/** Ops 子页 lazy 加载时的占位 UI。 */
function OpsSuspense({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-background text-sm text-muted-foreground">
          正在加载 Ops…
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

/** 四场景工作台路径前缀。 */
const SCENARIO_PATHS = ["/writing", "/agent", "/intel", "/collab"] as const;

function isOpsEvalPath(pathname: string): boolean {
  return /^\/ops\/[^/]+\/test(\/(runs\/[^/]+|history))?\/?$/.test(pathname);
}

function isOpsEvalReportPath(pathname: string): boolean {
  return /^\/ops\/[^/]+\/test\/runs\/[^/]+\/?$/.test(pathname);
}

function isOpsEvalHistoryPath(pathname: string): boolean {
  return /^\/ops\/[^/]+\/test\/history\/?$/.test(pathname);
}

function isOpsRetrievalPath(pathname: string): boolean {
  return /^\/ops\/[^/]+\/retrieval\/?$/.test(pathname);
}

function isOpsEnvelopePath(pathname: string): boolean {
  return /^\/ops\/[^/]+\/envelopes\/?$/.test(pathname);
}

function isOpsRawPath(pathname: string): boolean {
  return /^\/ops\/[^/]+\/raw\/?$/.test(pathname);
}

function isOpsOfficialPath(pathname: string): boolean {
  return /^\/ops\/[^/]+\/official(\/[^/]+)?\/?$/.test(pathname);
}

function isOpsWritingPath(pathname: string): boolean {
  return /^\/ops\/[^/]+\/writing\/?$/.test(pathname);
}


function AccountMenu() {
  const { user, logout, switchAccount } = useEndUserAuth();
  const { pathname, search } = useLocation();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        className="rounded-lg border border-input px-2 py-1 text-[11px] text-foreground/90 hover:bg-muted"
        title={user.id}
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((v) => !v)}
      >
        {user.username}
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-1 min-w-[160px] rounded-lg border border-border bg-popover py-1 shadow-lg"
        >
          <Link
            to="/settings"
            role="menuitem"
            className="block px-3 py-1.5 text-xs text-foreground hover:bg-muted"
            onClick={() => {
              if (!pathname.startsWith("/settings")) {
                rememberSettingsReturn(`${pathname}${search}`);
              }
              setOpen(false);
            }}
          >
            账户设置
          </Link>
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-1.5 text-left text-xs text-foreground hover:bg-muted"
            onClick={() => {
              setOpen(false);
              void switchAccount();
            }}
          >
            切换账号
          </button>
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-1.5 text-left text-xs text-destructive hover:bg-muted"
            onClick={() => {
              setOpen(false);
              void logout();
            }}
          >
            退出
          </button>
        </div>
      ) : null}
    </div>
  );
}

function Nav() {
  const { pathname, search } = useLocation();
  const scenario = scenarioMetaFromPath(pathname);
  useSiteBrand(
    pathname.startsWith("/settings")
      ? "设置"
      : scenario?.title ?? null,
  );
  const { sessionId, startNewSession, openSession } = useWorkbenchSession();
  const { open: toolsOpen, togglePanel, createAgent } =
    useAgentPanel();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  const linkCopiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const copySessionLink = async () => {
    if (!sessionId) return;
    const url = `${window.location.origin}${pathWithSession(pathname, sessionId)}`;
    let ok = false;
    try {
      await navigator.clipboard.writeText(url);
      ok = true;
    } catch {
      // Clipboard API needs a secure context (HTTPS/localhost). LAN HTTP falls here.
      try {
        const ta = document.createElement("textarea");
        ta.value = url;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        ok = document.execCommand("copy");
        document.body.removeChild(ta);
      } catch {
        ok = false;
      }
      if (!ok) {
        window.prompt("复制链接：", url);
        return;
      }
    }
    if (!ok) return;
    setLinkCopied(true);
    if (linkCopiedTimer.current) clearTimeout(linkCopiedTimer.current);
    linkCopiedTimer.current = setTimeout(() => setLinkCopied(false), 2000);
  };

  useEffect(
    () => () => {
      if (linkCopiedTimer.current) clearTimeout(linkCopiedTimer.current);
    },
    [],
  );

  const settingsActive =
    pathname === "/settings" || pathname.startsWith("/settings/");
  const workbenchHome = settingsActive
    ? readSettingsReturn(pathWithSession("/writing", sessionId))
    : pathWithSession("/writing", sessionId);

  return (
    <>
      <nav className="flex flex-wrap items-center gap-2 border-b border-border bg-background/80 px-6 py-3">
        <Link
          to={workbenchHome}
          className="mr-2 flex items-center gap-2.5 font-semibold tracking-tight text-foreground hover:opacity-90"
          aria-label={SITE_APP.name}
          title={settingsActive ? "返回工作台" : SITE_APP.name}
        >
          <SiteBrandMark site={SITE_APP} className="h-7 w-7 rounded-md" />
          <span className="text-base">{SITE_APP.name}</span>
        </Link>
        <Link
          to="/settings/model"
          className={`rounded-lg px-3 py-1.5 text-sm ${
            settingsActive
              ? "bg-muted text-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
          onClick={() => {
            if (!settingsActive) {
              rememberSettingsReturn(`${pathname}${search}`);
            }
          }}
        >
          设置
        </Link>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <ThemeSwitcher />
          <AccountMenu />
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
                variant="ghost"
                className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
                title="历史会话"
                aria-label="历史会话"
                onClick={() => {
                  setHistoryOpen(true);
                }}
              >
                <History className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className={`h-8 w-8 p-0 hover:text-foreground ${
                  toolsOpen
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground"
                }`}
                title={toolsOpen ? "收起工具时间线" : "打开工具时间线"}
                aria-label={toolsOpen ? "收起工具时间线" : "打开工具时间线"}
                aria-pressed={toolsOpen}
                onClick={() => togglePanel()}
              >
                <ListTree className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
                title="新建会话"
                aria-label="新建会话"
                onClick={() => void createAgent()}
              >
                <Plus className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 border-input px-2 text-xs text-foreground/90"
                onClick={() => void copySessionLink()}
              >
                {linkCopied ? "已复制" : "复制链接"}
              </Button>
            </>
          ) : null}
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

/**
 * 按 pathname 渲染主内容区（设置、场景工作台、短链重定向）。
 */
function MainContent() {
  const { pathname, search } = useLocation();

  if (pathname.startsWith("/s/")) {
    const sessionId = pathname.slice(3);
    return <Navigate to={`/writing?session=${sessionId}${search}`} replace />;
  }

  if (pathname === "/settings" || pathname.startsWith("/settings/")) {
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

/**
 * 已登录用户壳层：Nav + 按 sessionId key  remount WorkbenchProvider。
 */
function AppBody() {
  const { sessionId } = useWorkbenchSession();
  const { pathname } = useLocation();
  const lockViewport = SCENARIO_PATHS.includes(
    pathname as (typeof SCENARIO_PATHS)[number],
  );

  return (
    <WorkbenchProvider key={sessionId ?? "pending"}>
      <AgentPanelProvider>
        <div
          className={
            lockViewport
              ? "flex h-dvh min-h-0 flex-col overflow-hidden"
              : "min-h-screen"
          }
        >
          <div className={lockViewport ? "shrink-0" : undefined}>
            <Nav />
          </div>
          <div
            className={
              lockViewport ? "min-h-0 flex-1 overflow-hidden" : undefined
            }
          >
            <MainContent />
          </div>
        </div>
      </AgentPanelProvider>
    </WorkbenchProvider>
  );
}

/** 检查 EndUserAuth，未登录显示 LoginPage。 */
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

/**
 * 根路由入口：Ops 路径与用户工作台分流。
 * @returns Ops 懒加载页或 AuthenticatedApp
 */
export function App() {
  const { pathname } = useLocation();
  // I13: ops pages get their own boundary so an ops-only crash cannot take
  // down the user-facing workbench shell (and vice versa).
  const opsPage = isOpsEvalHistoryPath(pathname) ? (
    <EvalHistoryPage />
  ) : isOpsEvalReportPath(pathname) ? (
    <EvalRunReportPage />
  ) : isOpsEvalPath(pathname) ? (
    <EvalConsolePage />
  ) : isOpsRetrievalPath(pathname) ? (
    <RetrievalAuditPage />
  ) : isOpsEnvelopePath(pathname) ? (
    <EnvelopeAuditPage />
  ) : isOpsRawPath(pathname) ? (
    <RawAuditPage />
  ) : isOpsOfficialPath(pathname) ? (
    <OfficialBenchPage />
  ) : isOpsWritingPath(pathname) ? (
    <WritingSignalsLabPage />
  ) : null;
  if (opsPage !== null) {
    return (
      <ErrorBoundary label="Ops 页面">
        <OpsSuspense>{opsPage}</OpsSuspense>
      </ErrorBoundary>
    );
  }
  return <AuthenticatedApp />;
}
