import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useState } from "react";
import {
  activateModelProvider,
  createModelProvider,
  deleteModelProvider,
  listModelProviders,
  setAdminPassword as storeAdminPassword,
  updateModelProvider,
} from "../shared/api/client";

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

  useEffect(() => {
    if (error instanceof Error && error.message.includes("401")) {
      setAuthRequired(true);
    }
  }, [error]);

  const [label, setLabel] = useState("默认");
  const [provider, setProvider] = useState("anthropic");
  const [modelName, setModelName] = useState("claude-sonnet-4-20250514");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editModelName, setEditModelName] = useState("");

  const createMut = useMutation({
    mutationFn: createModelProvider,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["model-providers"] }),
  });

  const activateMut = useMutation({
    mutationFn: activateModelProvider,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["model-providers"] }),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { model_name: string } }) =>
      updateModelProvider(id, body),
    onSuccess: () => {
      setEditingId(null);
      void qc.invalidateQueries({ queryKey: ["model-providers"] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: deleteModelProvider,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["model-providers"] }),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!apiKey.trim()) return;
    createMut.mutate({
      label,
      provider,
      model_name: modelName,
      api_key: apiKey,
      base_url: baseUrl.trim() || undefined,
      activate: true,
    });
    setApiKey("");
  }

  return (
    <div className="mx-auto max-w-2xl p-6">
      <h1 className="text-2xl font-semibold">模型供应商</h1>
      <p className="mt-1 text-sm text-slate-400">
        保存后下一 Turn 起生效，无需重启容器。
      </p>

      {authRequired && (
        <form
          className="mt-4 flex gap-2 rounded-xl border border-amber-900/50 bg-amber-950/20 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!adminPasswordInput.trim()) return;
            storeAdminPassword(adminPasswordInput.trim());
            setAdminPasswordInput("");
            setAuthRequired(false);
            void qc.invalidateQueries({ queryKey: ["model-providers"] });
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
      )}

      <form
        onSubmit={onSubmit}
        className="mt-6 space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4"
      >
        <input
          className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          placeholder="标签"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
        <input
          className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          placeholder="provider"
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
        />
        <input
          className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          placeholder="model_name"
          value={modelName}
          onChange={(e) => setModelName(e.target.value)}
        />
        <input
          className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          placeholder="base_url（可选，OpenAI 兼容/中转填写，如 https://api.deepseek.com）"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
        />
        <input
          className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          placeholder="API Key（仅提交，不明文存储于浏览器）"
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
        <button
          type="submit"
          className="rounded-lg bg-sky-600 px-4 py-2 text-sm disabled:opacity-50"
          disabled={createMut.isPending}
        >
          保存并激活
        </button>
      </form>

      <section className="mt-8">
        <h2 className="text-sm font-medium text-slate-300">已保存</h2>
        {isLoading && <p className="text-sm text-slate-500">加载中…</p>}
        <ul className="mt-2 space-y-2">
          {providers.map((p) => (
            <li
              key={p.id}
              className="flex flex-col gap-2 rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between"
            >
              <div>
                <div className="font-medium">
                  {p.label}{" "}
                  {p.is_active && (
                    <span className="text-sky-400">(active)</span>
                  )}
                </div>
                <div className="text-xs text-slate-500">
                  {p.provider} / {p.model_name} · {p.api_key_hint}
                </div>
                {editingId === p.id ? (
                  <form
                    className="mt-2 flex gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (!editModelName.trim()) return;
                      updateMut.mutate({
                        id: p.id,
                        body: { model_name: editModelName.trim() },
                      });
                    }}
                  >
                    <input
                      className="flex-1 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs"
                      value={editModelName}
                      onChange={(e) => setEditModelName(e.target.value)}
                      placeholder="新 model_name"
                    />
                    <button
                      type="submit"
                      className="text-xs text-sky-400"
                      disabled={updateMut.isPending}
                    >
                      保存
                    </button>
                    <button
                      type="button"
                      className="text-xs text-slate-500"
                      onClick={() => setEditingId(null)}
                    >
                      取消
                    </button>
                  </form>
                ) : null}
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <button
                  type="button"
                  className="text-xs text-slate-400"
                  onClick={() => {
                    setEditingId(p.id);
                    setEditModelName(p.model_name);
                  }}
                >
                  编辑模型
                </button>
                {!p.is_active && (
                  <button
                    type="button"
                    className="text-xs text-sky-400"
                    onClick={() => activateMut.mutate(p.id)}
                  >
                    激活
                  </button>
                )}
                <button
                  type="button"
                  className="text-xs text-rose-400 disabled:opacity-50"
                  disabled={deleteMut.isPending || p.is_active}
                  onClick={() => deleteMut.mutate(p.id)}
                  title={p.is_active ? "不可删除当前 active 配置" : "删除"}
                >
                  删除
                </button>
              </div>
            </li>
          ))}
          {!providers.length && !isLoading && (
            <li className="text-sm text-slate-500">
              暂无配置（runtime 使用 .env fallback）
            </li>
          )}
        </ul>
      </section>
    </div>
  );
}
