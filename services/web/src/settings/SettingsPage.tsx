import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import type { ModelProvider } from "../shared/api/client";
import {
  activateModelProvider,
  changePassword,
  createModelProvider,
  deleteModelProvider,
  fetchDefaultWork,
  listModelProviders,
  updateModelProvider,
} from "../shared/api/client";
import { useEndUserAuth } from "../shared/auth/EndUserAuth";
import { useTheme } from "../shared/theme/ThemeProvider";
import type { ThemeId } from "../shared/theme/theme";

function formatContextWindow(tokens: number | null | undefined): string {
  if (tokens == null || tokens <= 0) return "默认";
  if (tokens >= 1000) return `${Math.round(tokens / 1000)}k`;
  return String(tokens);
}

function parseContextWindowInput(raw: string): number | undefined {
  const trimmed = raw.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed.replace(/_/g, ""));
  if (!Number.isFinite(parsed) || parsed < 4096) return undefined;
  return Math.floor(parsed);
}

const PROVIDER_SUGGESTIONS = [
  "anthropic",
  "openai",
  "deepseek",
  "moonshot",
  "zhipu",
  "azure",
  "ollama",
];

const MODEL_PRESETS: Record<string, string> = {
  anthropic: "claude-sonnet-4-20250514",
  openai: "gpt-4o-mini",
  deepseek: "deepseek-chat",
};

type ConfigDraft = {
  label: string;
  provider: string;
  modelName: string;
  baseUrl: string;
  contextWindowTokens: string;
  apiKey: string;
};

const EMPTY_DRAFT: ConfigDraft = {
  label: "",
  provider: "openai",
  modelName: MODEL_PRESETS.openai,
  baseUrl: "",
  contextWindowTokens: "",
  apiKey: "",
};

function draftFromProfile(p: ModelProvider): ConfigDraft {
  return {
    label: p.label,
    provider: p.provider,
    modelName: p.model_name,
    baseUrl: p.base_url ?? "",
    contextWindowTokens: p.context_window_tokens
      ? String(p.context_window_tokens)
      : "",
    apiKey: "",
  };
}

function profileSummary(p: ModelProvider): string {
  return `${p.provider} / ${p.model_name}`;
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
      {hint ? (
        <span className="block text-xs text-muted-foreground/80">{hint}</span>
      ) : null}
    </label>
  );
}

const inputClass =
  "w-full rounded border border-input bg-background px-3 py-2 text-sm text-foreground";

type SettingsTab = "account" | "appearance" | "model";

function tabFromPath(pathname: string): SettingsTab {
  if (pathname.endsWith("/model")) return "model";
  if (pathname.endsWith("/appearance")) return "appearance";
  return "account";
}

function AccountSection() {
  const { user } = useEndUserAuth();
  const work = useQuery({
    queryKey: ["works", "default"],
    queryFn: fetchDefaultWork,
    staleTime: 60_000,
  });

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [formOk, setFormOk] = useState<string | null>(null);

  const passwordMut = useMutation({
    mutationFn: () => changePassword(currentPassword, newPassword),
    onSuccess: () => {
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setFormError(null);
      setFormOk("密码已更新");
    },
    onError: (err: Error) => {
      setFormOk(null);
      setFormError(err.message || "修改失败");
    },
  });

  const onChangePassword = (e: FormEvent) => {
    e.preventDefault();
    setFormOk(null);
    if (newPassword.length < 6) {
      setFormError("新密码至少 6 位");
      return;
    }
    if (newPassword !== confirmPassword) {
      setFormError("两次输入的新密码不一致");
      return;
    }
    passwordMut.mutate();
  };

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-border bg-card/60 p-4">
        <h2 className="text-sm font-medium text-foreground">账户</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          当前登录身份与默认 Work（只读）。多租户隔离在服务端完成，此处不提供切换 Work。
        </p>
        <dl className="mt-4 space-y-2 text-sm">
          <div className="flex gap-2">
            <dt className="w-24 shrink-0 text-muted-foreground">用户名</dt>
            <dd className="text-foreground">{user?.username ?? "—"}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-24 shrink-0 text-muted-foreground">用户 ID</dt>
            <dd className="break-all font-mono text-xs text-foreground/90">
              {user?.id ?? "—"}
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-24 shrink-0 text-muted-foreground">默认 Work</dt>
            <dd className="min-w-0 text-foreground/90">
              {work.isLoading
                ? "加载中…"
                : work.isError
                  ? "无法加载"
                  : work.data
                    ? `${work.data.name} · ${work.data.id.slice(0, 8)}…`
                    : "—"}
            </dd>
          </div>
          {work.data?.work_root ? (
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-muted-foreground">Work 根</dt>
              <dd className="break-all font-mono text-[11px] text-muted-foreground">
                {work.data.work_root}
              </dd>
            </div>
          ) : null}
        </dl>
      </section>

      <section className="rounded-xl border border-border bg-card/60 p-4">
        <h2 className="text-sm font-medium text-foreground">修改密码</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          修改后当前登录仍然有效；下次登录请使用新密码。
        </p>
        <form className="mt-4 max-w-sm space-y-3" onSubmit={onChangePassword}>
          <Field label="当前密码">
            <input
              type="password"
              className={inputClass}
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </Field>
          <Field label="新密码" hint="至少 6 位">
            <input
              type="password"
              className={inputClass}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              required
              minLength={6}
            />
          </Field>
          <Field label="确认新密码">
            <input
              type="password"
              className={inputClass}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
              required
              minLength={6}
            />
          </Field>
          {formError ? (
            <p className="text-sm text-destructive">{formError}</p>
          ) : null}
          {formOk ? <p className="text-sm text-success">{formOk}</p> : null}
          <button
            type="submit"
            className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
            disabled={
              passwordMut.isPending ||
              !currentPassword ||
              newPassword.length < 6
            }
          >
            {passwordMut.isPending ? "保存中…" : "更新密码"}
          </button>
        </form>
      </section>
    </div>
  );
}

function AppearanceSection() {
  const { theme, setTheme, themes, meta } = useTheme();
  return (
    <section className="rounded-xl border border-border bg-card/60 p-4">
      <h2 className="text-sm font-medium text-foreground">外观</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        仅影响 Web 显示主题，不改变 Agent 交互与速率。偏好按账号保存在本机浏览器。
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        {themes.map((id: ThemeId) => {
          const selected = theme === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => setTheme(id)}
              className={`rounded-lg border px-3 py-2.5 text-left transition-colors ${
                selected
                  ? "border-primary/50 bg-primary/10 ring-1 ring-primary/40"
                  : "border-border bg-background hover:bg-muted"
              }`}
            >
              <span className="block text-sm font-medium text-foreground">
                {meta[id].label}
              </span>
              <span className="mt-0.5 block text-[11px] text-muted-foreground">
                {meta[id].description}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function ModelConfigForm({
  draft,
  onChange,
  onSubmit,
  onCancel,
  mode,
  apiKeyHint,
  pending,
  submitLabel,
  showActivateOnCreate,
  activateOnCreate,
  onActivateOnCreateChange,
}: {
  draft: ConfigDraft;
  onChange: (next: ConfigDraft) => void;
  onSubmit: (e: FormEvent) => void;
  onCancel?: () => void;
  mode: "create" | "update";
  apiKeyHint?: string;
  pending?: boolean;
  submitLabel?: string;
  showActivateOnCreate?: boolean;
  activateOnCreate?: boolean;
  onActivateOnCreateChange?: (value: boolean) => void;
}) {
  const [showKeyField, setShowKeyField] = useState(mode === "create");

  return (
    <form className="space-y-4" onSubmit={onSubmit}>
      <Field label="显示名称" hint="如「公司 OpenAI」「本地 DeepSeek」">
        <input
          className={inputClass}
          value={draft.label}
          onChange={(e) => onChange({ ...draft, label: e.target.value })}
          placeholder="我的模型配置"
        />
      </Field>

      <Field
        label="供应商"
        hint="从列表选择常见供应商；选「自定义」可填任意标识（小写英文）"
      >
        <select
          className={inputClass}
          value={
            PROVIDER_SUGGESTIONS.includes(draft.provider)
              ? draft.provider
              : "__custom__"
          }
          onChange={(e) => {
            const next = e.target.value;
            if (next === "__custom__") {
              onChange({
                ...draft,
                provider: PROVIDER_SUGGESTIONS.includes(draft.provider)
                  ? ""
                  : draft.provider,
              });
              return;
            }
            const preset = MODEL_PRESETS[next];
            onChange({
              ...draft,
              provider: next,
              ...(preset ? { modelName: preset } : {}),
            });
          }}
        >
          {PROVIDER_SUGGESTIONS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
          <option value="__custom__">自定义…</option>
        </select>
        {!PROVIDER_SUGGESTIONS.includes(draft.provider) ? (
          <input
            className={`${inputClass} mt-2`}
            value={draft.provider}
            onChange={(e) => {
              const next = e.target.value.trim().toLowerCase();
              const preset = MODEL_PRESETS[next];
              onChange({
                ...draft,
                provider: e.target.value,
                ...(preset && mode === "create" ? { modelName: preset } : {}),
              });
            }}
            placeholder="例如 my-provider"
            autoComplete="off"
          />
        ) : null}
      </Field>

      <Field label="模型" hint="填写该供应商下的 model id">
        <input
          className={inputClass}
          value={draft.modelName}
          onChange={(e) => onChange({ ...draft, modelName: e.target.value })}
          placeholder="gpt-4o-mini"
        />
      </Field>

      <Field label="上下文窗口（tokens）" hint="留空则使用模型或环境变量默认">
        <input
          className={inputClass}
          inputMode="numeric"
          value={draft.contextWindowTokens}
          onChange={(e) =>
            onChange({ ...draft, contextWindowTokens: e.target.value })
          }
          placeholder="128000"
        />
      </Field>

      <Field label="API 地址（可选）" hint="中转或私有部署时填写 base URL">
        <input
          className={inputClass}
          value={draft.baseUrl}
          onChange={(e) => onChange({ ...draft, baseUrl: e.target.value })}
          placeholder="https://api.openai.com/v1"
        />
      </Field>

      {mode === "create" || showKeyField ? (
        <Field
          label={mode === "create" ? "API Key" : "新 API Key"}
          hint={
            mode === "create"
              ? "新建配置必填"
              : `当前已保存 ${apiKeyHint ?? "••••"}；留空表示不修改`
          }
        >
          <input
            className={inputClass}
            type="password"
            autoComplete="off"
            value={draft.apiKey}
            onChange={(e) => onChange({ ...draft, apiKey: e.target.value })}
          />
        </Field>
      ) : (
        <button
          type="button"
          className="text-xs text-primary hover:text-primary"
          onClick={() => setShowKeyField(true)}
        >
          需要更换 API Key？
        </button>
      )}

      {showActivateOnCreate ? (
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={activateOnCreate}
            onChange={(e) => onActivateOnCreateChange?.(e.target.checked)}
          />
          保存后设为当前使用的模型
        </label>
      ) : null}

      <div className="flex flex-wrap gap-2 pt-1">
        <button
          type="submit"
          className="rounded-lg bg-primary px-4 py-2 text-sm disabled:opacity-50"
          disabled={
            pending ||
            !draft.label.trim() ||
            !draft.provider.trim() ||
            !draft.modelName.trim() ||
            (mode === "create" && !draft.apiKey.trim())
          }
        >
          {submitLabel ?? (mode === "create" ? "保存" : "保存修改")}
        </button>
        {onCancel ? (
          <button
            type="button"
            className="rounded-lg border border-input px-4 py-2 text-sm text-muted-foreground"
            onClick={onCancel}
          >
            取消
          </button>
        ) : null}
      </div>
    </form>
  );
}

type PanelMode = "view" | "edit" | "create";

export function SettingsPage() {
  const qc = useQueryClient();
  const { pathname } = useLocation();
  const tab = tabFromPath(pathname);
  const [loginRequired, setLoginRequired] = useState(false);
  const {
    data: providers = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["model-providers"],
    queryFn: listModelProviders,
    retry: false,
    enabled: tab === "model",
  });

  const sortedProviders = useMemo(
    () =>
      [...providers].sort((a, b) => {
        if (a.is_active !== b.is_active) return a.is_active ? -1 : 1;
        return (
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
        );
      }),
    [providers],
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [panelMode, setPanelMode] = useState<PanelMode>("view");
  const [draft, setDraft] = useState<ConfigDraft>(EMPTY_DRAFT);
  const [activateOnCreate, setActivateOnCreate] = useState(false);

  const selectedProvider =
    selectedId != null
      ? (providers.find((p) => p.id === selectedId) ?? null)
      : null;

  useEffect(() => {
    if (error instanceof Error && error.message.includes("401")) {
      setLoginRequired(true);
    }
  }, [error]);

  useEffect(() => {
    if (isLoading || providers.length === 0) return;
    if (selectedId && providers.some((p) => p.id === selectedId)) return;
    const active = providers.find((p) => p.is_active);
    setSelectedId(active?.id ?? providers[0].id);
    setPanelMode("view");
  }, [isLoading, providers, selectedId]);

  useEffect(() => {
    if (providers.length === 0 && !isLoading && !loginRequired) {
      setPanelMode("create");
      setDraft(EMPTY_DRAFT);
      setActivateOnCreate(true);
    }
  }, [providers.length, isLoading, loginRequired]);

  const invalidate = () =>
    void qc.invalidateQueries({ queryKey: ["model-providers"] });

  const onMutationError = (err: Error) => {
    if (err.message.includes("401")) {
      setLoginRequired(true);
    }
  };

  const createMut = useMutation({
    mutationFn: createModelProvider,
    onSuccess: (created: ModelProvider) => {
      setSelectedId(created.id);
      setPanelMode("view");
      invalidate();
    },
    onError: onMutationError,
  });

  const updateMut = useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string;
      body: Parameters<typeof updateModelProvider>[1];
    }) => updateModelProvider(id, body),
    onSuccess: () => {
      setPanelMode("view");
      invalidate();
    },
    onError: onMutationError,
  });

  const activateMut = useMutation({
    mutationFn: activateModelProvider,
    onSuccess: () => invalidate(),
    onError: onMutationError,
  });

  const deleteMut = useMutation({
    mutationFn: deleteModelProvider,
    onSuccess: () => {
      setSelectedId(null);
      setPanelMode("view");
      invalidate();
    },
    onError: onMutationError,
  });

  const actionError =
    createMut.error ??
    updateMut.error ??
    activateMut.error ??
    deleteMut.error;

  function startCreate() {
    setSelectedId(null);
    setPanelMode("create");
    setDraft({ ...EMPTY_DRAFT, label: `配置 ${providers.length + 1}` });
    setActivateOnCreate(providers.length === 0);
  }

  function startEdit() {
    if (!selectedProvider) return;
    setDraft(draftFromProfile(selectedProvider));
    setPanelMode("edit");
  }

  function cancelPanel() {
    if (providers.length === 0) {
      setPanelMode("create");
      setDraft(EMPTY_DRAFT);
      return;
    }
    setPanelMode("view");
    if (selectedProvider) setDraft(draftFromProfile(selectedProvider));
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const windowTokens = parseContextWindowInput(draft.contextWindowTokens);
    const body = {
      label: draft.label.trim(),
      provider: draft.provider.trim(),
      model_name: draft.modelName.trim(),
      base_url: draft.baseUrl.trim() || undefined,
      ...(draft.apiKey.trim() ? { api_key: draft.apiKey.trim() } : {}),
      ...(windowTokens !== undefined
        ? { context_window_tokens: windowTokens }
        : {}),
    };

    if (panelMode === "edit" && selectedProvider) {
      updateMut.mutate({ id: selectedProvider.id, body });
      return;
    }

    if (panelMode === "create") {
      if (!draft.apiKey.trim()) return;
      createMut.mutate({
        ...body,
        api_key: draft.apiKey.trim(),
        activate: activateOnCreate,
      });
    }
  }

  const pending =
    createMut.isPending ||
    updateMut.isPending ||
    activateMut.isPending ||
    deleteMut.isPending;

  return (
    <div className="mx-auto max-w-4xl p-6">
      <h1 className="text-2xl font-semibold">设置</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        个人账户、外观与模型供应商。主题与本机会话偏好按账号隔离。
      </p>

      <nav className="mt-6 flex flex-wrap gap-2 border-b border-border pb-3">
        {(
          [
            { id: "account" as const, to: "/settings", label: "账户" },
            {
              id: "appearance" as const,
              to: "/settings/appearance",
              label: "外观",
            },
            { id: "model" as const, to: "/settings/model", label: "模型" },
          ] as const
        ).map((item) => (
          <Link
            key={item.id}
            to={item.to}
            className={`rounded-lg px-3 py-1.5 text-sm ${
              tab === item.id
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      {tab === "account" ? (
        <div className="mt-6">
          <AccountSection />
        </div>
      ) : null}

      {tab === "appearance" ? (
        <div className="mt-6">
          <AppearanceSection />
        </div>
      ) : null}

      {tab === "model" ? (
        <>
          <h2 className="mt-6 text-lg font-semibold">模型供应商</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            配置归属于当前登录用户；保存后下一 Turn 起生效。
          </p>

          {loginRequired ? (
            <div className="mt-4 space-y-2 rounded-xl border border-warning/40 bg-warning-muted p-4">
              <p className="text-sm text-warning">
                请先使用工作台账号登录后再管理模型配置。
              </p>
              <Link
                to="/writing"
                className="inline-block rounded-lg bg-warning px-4 py-2 text-sm text-warning-foreground"
              >
                去登录
              </Link>
            </div>
          ) : null}

          {actionError ? (
            <p className="mt-4 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              保存失败：{actionError.message}
              {actionError.message.includes("401")
                ? " — 请先登录工作台账号"
                : ""}
            </p>
          ) : null}

          {isLoading ? (
            <p className="mt-6 text-sm text-muted-foreground">加载中…</p>
          ) : loginRequired ? null : (
            <div className="mt-6 grid gap-4 md:grid-cols-[minmax(220px,260px)_minmax(0,1fr)]">
              <aside className="rounded-xl border border-border bg-background p-3">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    已保存配置
                  </h2>
                  <button
                    type="button"
                    className="rounded-md bg-primary/20 px-2 py-1 text-xs text-primary hover:bg-primary/30"
                    onClick={startCreate}
                  >
                    + 添加
                  </button>
                </div>
                {sortedProviders.length === 0 ? (
                  <p className="text-xs text-muted-foreground/80">
                    暂无，请添加第一条配置
                  </p>
                ) : (
                  <ul className="space-y-1">
                    {sortedProviders.map((p) => {
                      const selected =
                        selectedId === p.id && panelMode !== "create";
                      return (
                        <li key={p.id}>
                          <button
                            type="button"
                            className={`w-full rounded-lg px-2 py-2 text-left text-sm transition-colors ${
                              selected
                                ? "bg-primary/15 ring-1 ring-primary/40"
                                : "hover:bg-muted"
                            }`}
                            onClick={() => {
                              setSelectedId(p.id);
                              setPanelMode("view");
                            }}
                          >
                            <div className="flex items-center gap-2">
                              <span className="truncate font-medium text-foreground">
                                {p.label}
                              </span>
                              {p.is_active ? (
                                <span className="shrink-0 rounded bg-primary/25 px-1.5 py-0.5 text-[10px] text-primary">
                                  当前
                                </span>
                              ) : null}
                            </div>
                            <p className="mt-0.5 truncate text-xs text-muted-foreground">
                              {profileSummary(p)}
                            </p>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </aside>

              <section className="rounded-xl border border-border bg-card/60 p-4">
                {panelMode === "create" ? (
                  <>
                    <h2 className="mb-4 text-sm font-medium text-foreground/90">
                      添加模型配置
                    </h2>
                    <ModelConfigForm
                      draft={draft}
                      onChange={setDraft}
                      onSubmit={onSubmit}
                      onCancel={providers.length > 0 ? cancelPanel : undefined}
                      mode="create"
                      pending={pending}
                      submitLabel="保存配置"
                      showActivateOnCreate={providers.length > 0}
                      activateOnCreate={activateOnCreate}
                      onActivateOnCreateChange={setActivateOnCreate}
                    />
                  </>
                ) : selectedProvider && panelMode === "view" ? (
                  <>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-xs text-muted-foreground">配置详情</p>
                        <h2 className="mt-1 text-lg font-medium text-foreground">
                          {selectedProvider.label}
                        </h2>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {!selectedProvider.is_active ? (
                          <button
                            type="button"
                            className="rounded-lg bg-primary px-3 py-1.5 text-xs disabled:opacity-50"
                            disabled={pending}
                            onClick={() =>
                              activateMut.mutate(selectedProvider.id)
                            }
                          >
                            设为当前
                          </button>
                        ) : null}
                        <button
                          type="button"
                          className="rounded-lg border border-input px-3 py-1.5 text-xs text-foreground/90"
                          onClick={startEdit}
                        >
                          编辑
                        </button>
                        {!selectedProvider.is_active ? (
                          <button
                            type="button"
                            className="rounded-lg border border-destructive/40 px-3 py-1.5 text-xs text-destructive disabled:opacity-50"
                            disabled={pending}
                            onClick={() => {
                              if (
                                window.confirm(
                                  `确定删除「${selectedProvider.label}」？`,
                                )
                              ) {
                                deleteMut.mutate(selectedProvider.id);
                              }
                            }}
                          >
                            删除
                          </button>
                        ) : null}
                      </div>
                    </div>
                    <dl className="mt-4 space-y-2 text-sm">
                      <div className="flex gap-2">
                        <dt className="w-24 shrink-0 text-muted-foreground">
                          供应商
                        </dt>
                        <dd className="text-foreground/90">
                          {selectedProvider.provider}
                        </dd>
                      </div>
                      <div className="flex gap-2">
                        <dt className="w-24 shrink-0 text-muted-foreground">模型</dt>
                        <dd className="text-foreground/90">
                          {selectedProvider.model_name}
                        </dd>
                      </div>
                      <div className="flex gap-2">
                        <dt className="w-24 shrink-0 text-muted-foreground">
                          API Key
                        </dt>
                        <dd className="text-foreground/90">
                          已保存 {selectedProvider.api_key_hint}
                        </dd>
                      </div>
                      <div className="flex gap-2">
                        <dt className="w-24 shrink-0 text-muted-foreground">
                          上下文窗口
                        </dt>
                        <dd className="text-foreground/90">
                          {formatContextWindow(
                            selectedProvider.context_window_tokens,
                          )}
                        </dd>
                      </div>
                      {selectedProvider.base_url ? (
                        <div className="flex gap-2">
                          <dt className="w-24 shrink-0 text-muted-foreground">
                            API 地址
                          </dt>
                          <dd className="break-all text-foreground/90">
                            {selectedProvider.base_url}
                          </dd>
                        </div>
                      ) : null}
                    </dl>
                  </>
                ) : selectedProvider && panelMode === "edit" ? (
                  <>
                    <h2 className="mb-4 text-sm font-medium text-foreground/90">
                      编辑「{selectedProvider.label}」
                    </h2>
                    <ModelConfigForm
                      draft={draft}
                      onChange={setDraft}
                      onSubmit={onSubmit}
                      onCancel={cancelPanel}
                      mode="update"
                      apiKeyHint={selectedProvider.api_key_hint}
                      pending={pending}
                    />
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    从左侧选择配置，或添加新配置。
                  </p>
                )}
              </section>
            </div>
          )}

          {!isLoading && providers.length === 0 ? (
            <p className="mt-4 text-xs text-muted-foreground/80">
              未配置时 runtime 使用 .env 中的 MODEL_* fallback。
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
