import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiAuthHeaders, API_BASE } from "../shared/api/client";
import { throwIfNotOk } from "../shared/api/httpErrors";

const sessionInit = { credentials: "include" as RequestCredentials };

export type CommandAllowPrefix = {
  id: string;
  prefix: string;
  created_at: string;
};

async function listCommandAllowlist(): Promise<CommandAllowPrefix[]> {
  const res = await fetch(`${API_BASE}/settings/command-allowlist`, sessionInit);
  await throwIfNotOk(res, "listCommandAllowlist");
  return res.json() as Promise<CommandAllowPrefix[]>;
}

async function addCommandAllowPrefix(prefix: string): Promise<CommandAllowPrefix> {
  const res = await fetch(`${API_BASE}/settings/command-allowlist`, {
    ...sessionInit,
    method: "POST",
    headers: apiAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ prefix }),
  });
  await throwIfNotOk(res, "addCommandAllowPrefix");
  return res.json() as Promise<CommandAllowPrefix>;
}

async function deleteCommandAllowPrefix(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/settings/command-allowlist/${id}`, {
    ...sessionInit,
    method: "DELETE",
  });
  if (res.status === 204) return;
  await throwIfNotOk(res, "deleteCommandAllowPrefix");
}

export function CommandAllowlistCard() {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const list = useQuery({
    queryKey: ["command-allowlist"],
    queryFn: listCommandAllowlist,
  });
  const add = useMutation({
    mutationFn: addCommandAllowPrefix,
    onSuccess: () => {
      setDraft("");
      void queryClient.invalidateQueries({ queryKey: ["command-allowlist"] });
    },
  });
  const remove = useMutation({
    mutationFn: deleteCommandAllowPrefix,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["command-allowlist"] });
    },
  });
  const rows = list.data ?? [];

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-lg font-semibold">命令允许列表</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          审批时选择「加入允许列表」会按命令前缀记住。之后以该前缀开头的
          <code className="mx-1 text-xs">run_command</code>
          不再询问。前缀按空格分界：
          <code className="mx-1 text-xs">pytest</code>
          匹配
          <code className="mx-1 text-xs">pytest -q</code>
          ，不匹配
          <code className="mx-1 text-xs">python3</code>。
        </p>
      </div>

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const prefix = draft.trim();
          if (!prefix) return;
          add.mutate(prefix);
        }}
      >
        <input
          className="min-w-[12rem] flex-1 rounded border border-input bg-background px-3 py-2 text-sm"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="例如 pytest 或 npm test"
          maxLength={200}
        />
        <button
          type="submit"
          className="rounded-lg bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
          disabled={add.isPending || !draft.trim()}
        >
          添加前缀
        </button>
      </form>

      {list.isError ? (
        <p className="text-sm text-destructive">无法加载允许列表，请确认已登录。</p>
      ) : null}
      {add.isError ? (
        <p className="text-sm text-destructive">添加失败。</p>
      ) : null}

      {list.isLoading ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">还没有前缀。审批命令时可以选择加入。</p>
      ) : (
        <ul className="divide-y divide-border rounded-xl border border-border">
          {rows.map((row) => (
            <li
              key={row.id}
              className="flex items-center justify-between gap-3 px-3 py-2"
            >
              <code className="min-w-0 truncate text-sm">{row.prefix}</code>
              <button
                type="button"
                className="shrink-0 text-xs text-destructive hover:underline"
                disabled={remove.isPending}
                onClick={() => remove.mutate(row.id)}
              >
                删除
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
