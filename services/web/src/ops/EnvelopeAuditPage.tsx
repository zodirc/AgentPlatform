import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { OpsShell, secretFromOpsPath } from "./OpsShell";

type EnvelopeItem = {
  step_index: number;
  content_hash: string;
  fill_ratio?: number | null;
  has_full_envelope: boolean;
  envelope?: unknown;
  created_at?: string | null;
};

type EnvelopeResponse = {
  turn_id: string;
  count: number;
  envelopes: EnvelopeItem[];
};

type RecentItem = {
  turn_id: string;
  session_id: string;
  scenario_id?: string;
  status?: string;
  user_preview?: string | null;
  owner_user_id?: string | null;
  envelope_count: number;
  full_count: number;
  last_at?: string | null;
  max_fill_ratio?: number | null;
};

function authHeaders(secret: string): HeadersInit {
  return { Authorization: `Bearer ${secret}` };
}

export function EnvelopeAuditPage() {
  const { pathname } = useLocation();
  const secret = secretFromOpsPath(pathname);
  const [turnId, setTurnId] = useState("");
  const [recent, setRecent] = useState<RecentItem[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<EnvelopeResponse | null>(null);

  const loadRecent = useCallback(async () => {
    if (!secret) return;
    setListLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/v1/ops/envelopes/recent?limit=40", {
        headers: authHeaders(secret),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `HTTP ${res.status}`);
      }
      const body = (await res.json()) as { items?: RecentItem[]; error?: string };
      setRecent(body.items || []);
      if (body.error) setError(body.error);
    } catch (e) {
      setRecent([]);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setListLoading(false);
    }
  }, [secret]);

  useEffect(() => {
    void loadRecent();
  }, [loadRecent]);

  const loadTurn = useCallback(
    async (id: string) => {
      const trimmed = id.trim();
      if (!trimmed || !secret) return;
      setTurnId(trimmed);
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/v1/ops/envelopes/turns/${encodeURIComponent(trimmed)}`, {
          headers: authHeaders(secret),
        });
        if (!res.ok) {
          const body = await res.text();
          throw new Error(body || `HTTP ${res.status}`);
        }
        setData((await res.json()) as EnvelopeResponse);
      } catch (e) {
        setData(null);
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [secret],
  );

  return (
    <OpsShell
      secret={secret}
      title="模型信封"
      subtitle="最近有信封落盘的 Turn · 点开看哈希 / 全量抽样（HM4）"
    >
      <div className="mb-4 flex flex-wrap gap-2">
        <button
          type="button"
          className="rounded-md border border-border px-3 py-2 text-sm hover:bg-muted disabled:opacity-50"
          onClick={() => void loadRecent()}
          disabled={listLoading}
        >
          {listLoading ? "刷新中…" : "刷新列表"}
        </button>
      </div>

      <div className="mb-4 rounded-md border border-border">
        <div className="border-b border-border px-3 py-2 text-xs font-medium text-muted-foreground">
          最近信封 Turn（{recent.length}）
        </div>
        {!recent.length && !listLoading ? (
          <p className="px-3 py-4 text-sm text-muted-foreground">
            暂无信封。默认低采样；高 fill / debug 会更容易落盘。
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {recent.map((item) => {
              const selected = data?.turn_id === item.turn_id;
              return (
                <li key={item.turn_id}>
                  <button
                    type="button"
                    onClick={() => void loadTurn(item.turn_id)}
                    className={`w-full px-3 py-2.5 text-left text-sm hover:bg-muted/60 ${
                      selected ? "bg-primary/10" : ""
                    }`}
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="font-medium text-foreground">
                        {item.user_preview || "(no preview)"}
                      </span>
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {item.last_at || "—"}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[11px] text-muted-foreground">
                      <span>{item.scenario_id}</span>
                      <span>
                        env={item.envelope_count} full={item.full_count}
                      </span>
                      {item.max_fill_ratio != null ? (
                        <span>max_fill={item.max_fill_ratio}</span>
                      ) : null}
                      <span className="truncate">{item.turn_id}</span>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <details className="mb-4 rounded-md border border-border px-3 py-2 text-sm">
        <summary className="cursor-pointer text-muted-foreground">精确跳转（可选 turn_id）</summary>
        <div className="mt-2 flex flex-wrap gap-2">
          <input
            className="min-w-[280px] flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm font-mono"
            placeholder="turn_id (UUID)"
            value={turnId}
            onChange={(e) => setTurnId(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void loadTurn(turnId);
            }}
          />
          <button
            type="button"
            className="rounded-md border border-border px-3 py-2 text-sm hover:bg-muted disabled:opacity-50"
            onClick={() => void loadTurn(turnId)}
            disabled={loading || !turnId.trim()}
          >
            {loading ? "加载中…" : "打开"}
          </button>
        </div>
      </details>

      {error ? <p className="mb-4 text-sm text-destructive">{error}</p> : null}

      {data ? (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            turn={data.turn_id} · envelopes={data.count}
          </p>
          {data.envelopes.map((item, i) => (
            <div
              key={`${item.step_index}-${item.content_hash}-${i}`}
              className="rounded-md border border-border bg-card px-3 py-2 text-xs"
            >
              <div className="flex flex-wrap gap-2 font-mono text-[11px]">
                <span>step={item.step_index}</span>
                <span className="truncate">hash={item.content_hash}</span>
                {item.fill_ratio != null ? <span>fill={item.fill_ratio}</span> : null}
                <span>{item.has_full_envelope ? "full" : "hash-only"}</span>
              </div>
              {item.has_full_envelope ? (
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-[10px] text-muted-foreground">
                  {JSON.stringify(item.envelope, null, 2)}
                </pre>
              ) : null}
            </div>
          ))}
          {!data.envelopes.length ? (
            <p className="text-sm text-muted-foreground">该 Turn 无信封记录。</p>
          ) : null}
        </div>
      ) : null}
    </OpsShell>
  );
}
