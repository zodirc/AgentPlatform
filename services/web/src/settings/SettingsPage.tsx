import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState, type ReactNode } from "react";
import type { ModelProvider } from "../shared/api/client";
import {
  activateModelProvider,
  createModelProvider,
  deleteModelProvider,
  listModelProviders,
  setAdminPassword as storeAdminPassword,
  updateModelProvider,
} from "../shared/api/client";

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
      <span className="text-xs font-medium text-slate-400">{label}</span>
      {children}
      {hint ? (
        <span className="block text-xs text-slate-600">{hint}</span>
      ) : null}
    </label>
  );
}

const inputClass =
  "w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100";

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
        hint="可从列表选择常见供应商，也可直接输入自定义标识（小写英文）"
      >
        <input
          className={inputClass}
          list="provider-suggestions"
          value={draft.provider}
          onChange={(e) => {
            const next = e.target.value;
            const preset = MODEL_PRESETS[next];
            onChange({
              ...draft,
              provider: next,
              ...(preset && mode === "create" ? { modelName: preset } : {}),
            });
          }}
          placeholder="openai"
        />
        <datalist id="provider-suggestions">
          {PROVIDER_SUGGESTIONS.map((p) => (
            <option key={p} value={p} />
          ))}
        </datalist>
      </Field>

      <Field label="模型" hint="填写该供应商下的 model id">
        <input
          className={inputClass}
          value={draft.modelName}
          onChange={(e) => onChange({ ...draft, modelName: e.target.value })}
          placeholder="gpt-4o-mini"
        />
      </Field>

      <Field
        label="上下文窗口（tokens）"
        hint="留空则使用模型或环境变量默认"
      >
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
          className="text-xs text-sky-400 hover:text-sky-300"
          onClick={() => setShowKeyField(true)}
        >
          需要更换 API Key？
        </button>
      )}

      {showActivateOnCreate ? (
        <label className="flex items-center gap-2 text-sm text-slate-400">
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
          className="rounded-lg bg-sky-600 px-4 py-2 text-sm disabled:opacity-50"
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
            className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-400"
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
  const [adminPasswordInput, setAdminPasswordInput] = useState("");
  const [authRequired, setAuthRequired] = useState(false);
  const {
    data: providers = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["model-providers"],
    queryFn: listModelProviders,
    retry: false,
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
      setAuthRequired(true);
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
    if (providers.length === 0 && !isLoading) {
      setPanelMode("create");
      setDraft(EMPTY_DRAFT);
      setActivateOnCreate(true);
    }
  }, [providers.length, isLoading]);

  const invalidate = () =>
    void qc.invalidateQueries({ queryKey: ["model-providers"] });

  const createMut = useMutation({
    mutationFn: createModelProvider,
    onSuccess: (created: ModelProvider) => {
      setSelectedId(created.id);
      setPanelMode("view");
      invalidate();
    },
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
  });

  const activateMut = useMutation({
    mutationFn: activateModelProvider,
    onSuccess: () => invalidate(),
  });

  const deleteMut = useMutation({
    mutationFn: deleteModelProvider,
    onSuccess: () => {
      setSelectedId(null);
      setPanelMode("view");
      invalidate();
    },
  });

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
      <h1 className="text-2xl font-semibold">模型供应商</h1>
      <p className="mt-1 text-sm text-slate-400">
        可保存多条配置并切换当前使用的模型；保存后下一 Turn 起生效。
      </p>

      {authRequired ? (
        <form
          className="mt-4 flex gap-2 rounded-xl border border-amber-900/50 bg-amber-950/20 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!adminPasswordInput.trim()) return;
            storeAdminPassword(adminPasswordInput.trim());
            setAdminPasswordInput("");
            setAuthRequired(false);
            invalidate();
          }}
        >
          <input
            className="flex-1 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            type="password"
            placeholder="Admin 密码（AUTH_ENABLED）"
            value={adminPasswordInput}
            onChange={(e) => setAdminPasswordInput(e.target.value)}
          />
          <button
            type="submit"
            className="rounded-lg bg-amber-700 px-4 py-2 text-sm"
          >
            解锁
          </button>
        </form>
      ) : null}

      {isLoading ? (
        <p className="mt-6 text-sm text-slate-500">加载中…</p>
      ) : (
        <div className="mt-6 grid gap-4 md:grid-cols-[minmax(220px,260px)_minmax(0,1fr)]">
          <aside className="rounded-xl border border-slate-800 bg-slate-950 p-3">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="text-xs font-medium uppercase tracking-wide text-slate-500">
                已保存配置
              </h2>
              <button
                type="button"
                className="rounded-md bg-sky-900/50 px-2 py-1 text-xs text-sky-200 hover:bg-sky-900"
                onClick={startCreate}
              >
                + 添加
              </button>
            </div>
            {sortedProviders.length === 0 ? (
              <p className="text-xs text-slate-600">暂无，请添加第一条配置</p>
            ) : (
              <ul className="space-y-1">
                {sortedProviders.map((p) => {
                  const selected = selectedId === p.id && panelMode !== "create";
                  return (
                    <li key={p.id}>
                      <button
                        type="button"
                        className={`w-full rounded-lg px-2 py-2 text-left text-sm transition-colors ${
                          selected
                            ? "bg-sky-950/50 ring-1 ring-sky-800/60"
                            : "hover:bg-slate-900"
                        }`}
                        onClick={() => {
                          setSelectedId(p.id);
                          setPanelMode("view");
                        }}
                      >
                        <div className="flex items-center gap-2">
                          <span className="truncate font-medium text-slate-200">
                            {p.label}
                          </span>
                          {p.is_active ? (
                            <span className="shrink-0 rounded bg-sky-900/60 px-1.5 py-0.5 text-[10px] text-sky-300">
                              当前
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-0.5 truncate text-xs text-slate-500">
                          {profileSummary(p)}
                        </p>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </aside>

          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            {panelMode === "create" ? (
              <>
                <h2 className="mb-4 text-sm font-medium text-slate-300">
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
                    <p className="text-xs text-slate-500">配置详情</p>
                    <h2 className="mt-1 text-lg font-medium text-slate-100">
                      {selectedProvider.label}
                    </h2>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {!selectedProvider.is_active ? (
                      <button
                        type="button"
                        className="rounded-lg bg-sky-600 px-3 py-1.5 text-xs disabled:opacity-50"
                        disabled={pending}
                        onClick={() => activateMut.mutate(selectedProvider.id)}
                      >
                        设为当前
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300"
                      onClick={startEdit}
                    >
                      编辑
                    </button>
                    {!selectedProvider.is_active ? (
                      <button
                        type="button"
                        className="rounded-lg border border-rose-900/60 px-3 py-1.5 text-xs text-rose-400 disabled:opacity-50"
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
                    <dt className="w-24 shrink-0 text-slate-500">供应商</dt>
                    <dd className="text-slate-300">{selectedProvider.provider}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-24 shrink-0 text-slate-500">模型</dt>
                    <dd className="text-slate-300">
                      {selectedProvider.model_name}
                    </dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-24 shrink-0 text-slate-500">API Key</dt>
                    <dd className="text-slate-300">
                      已保存 {selectedProvider.api_key_hint}
                    </dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-24 shrink-0 text-slate-500">上下文窗口</dt>
                    <dd className="text-slate-300">
                      {formatContextWindow(
                        selectedProvider.context_window_tokens,
                      )}
                    </dd>
                  </div>
                  {selectedProvider.base_url ? (
                    <div className="flex gap-2">
                      <dt className="w-24 shrink-0 text-slate-500">API 地址</dt>
                      <dd className="break-all text-slate-300">
                        {selectedProvider.base_url}
                      </dd>
                    </div>
                  ) : null}
                </dl>
              </>
            ) : selectedProvider && panelMode === "edit" ? (
              <>
                <h2 className="mb-4 text-sm font-medium text-slate-300">
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
              <p className="text-sm text-slate-500">
                从左侧选择配置，或添加新配置。
              </p>
            )}
          </section>
        </div>
      )}

      {!isLoading && providers.length === 0 ? (
        <p className="mt-4 text-xs text-slate-600">
          未配置时 runtime 使用 .env 中的 MODEL_* fallback。
        </p>
      ) : null}
    </div>
  );
}
