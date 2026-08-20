import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { OpsShell, secretFromOpsPath } from "./OpsShell";

const FRAGMENTS: { id: string; label: string }[] = [
  { id: "plot_progress", label: "情节推进" },
  { id: "worldview_texture", label: "世界观" },
  { id: "climax_beat", label: "高潮" },
  { id: "battle_action", label: "战斗/动作" },
  { id: "dialogue_dyad", label: "两人对话" },
  { id: "mixed", label: "混合" },
];

const DIMENSIONS: { id: string; label: string }[] = [
  { id: "structure", label: "结构" },
  { id: "character", label: "人物" },
  { id: "pacing", label: "节奏" },
  { id: "voice", label: "声口" },
  { id: "exemplar_alignment", label: "范本贴近" },
];

const PENALTY_SIGNALS: { id: string; label: string; magnitude: number }[] = [
  { id: "hinge_dense", label: "铰链句过密", magnitude: -0.12 },
  { id: "staccato_uniform", label: "短句节奏单一", magnitude: -0.15 },
  { id: "opening_institution", label: "开篇机构腔", magnitude: -0.1 },
  { id: "lore_dump", label: "设定堆砌", magnitude: -0.1 },
  { id: "length_short", label: "篇幅过短", magnitude: -0.08 },
  { id: "meta_knowing_high", label: "元叙事过多", magnitude: -0.06 },
  { id: "glue_heavy", label: "过渡胶过多", magnitude: -0.05 },
  { id: "fragment_mismatch", label: "片段类型不符", magnitude: -0.1 },
];

const REWARD_SIGNALS: { id: string; label: string; magnitude: number }[] = [
  { id: "scene_ratio_high", label: "场景描写比高", magnitude: 0.08 },
  { id: "dialogue_rhythm_varied", label: "对话节奏多样", magnitude: 0.1 },
  { id: "exemplar_alignment_high", label: "范本贴近度高", magnitude: 0.12 },
  { id: "outline_duty_match", label: "大纲职责匹配", magnitude: 0.1 },
  { id: "character_card_action", label: "人物卡行动一致", magnitude: 0.08 },
];

type LabPrefs = {
  fragment_weights: Record<string, Record<string, number>>;
  signal_penalties: Record<string, Record<string, number>>;
  signal_rewards: Record<string, Record<string, number>>;
};

function clonePrefs(raw: unknown): LabPrefs | null {
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;
  const weights = obj.fragment_weights;
  const penalties = obj.signal_penalties;
  const rewards = obj.signal_rewards;
  if (!weights || typeof weights !== "object") return null;
  return {
    fragment_weights: JSON.parse(JSON.stringify(weights)),
    signal_penalties: JSON.parse(JSON.stringify(penalties || {})),
    signal_rewards: JSON.parse(JSON.stringify(rewards || {})),
  };
}

type ExemplarItem = {
  fragment: string;
  slug: string;
  author: string;
  work: string;
  beat: string;
  license?: string;
  text: string;
};

type SignalHit = {
  key: string;
  hit?: boolean;
  delta?: number;
  hint?: string;
};

type ScoreResponse = {
  source?: {
    kind?: string;
    slug?: string;
    author?: string;
    work?: string;
    beat?: string;
    fragment?: string;
  };
  persisted?: boolean;
  writing_signals?: {
    fragment?: { declared?: string; detected?: string; mismatch?: boolean };
    dimensions?: Record<string, number>;
    dimension_weights?: Record<string, number>;
    penalties?: SignalHit[];
    rewards?: SignalHit[];
    composite?: number;
    net_signal?: number;
    exemplar_fit?: {
      score?: number;
      n?: number;
      nearest?: { author?: string; work?: string; beat?: string; id?: string };
    };
  };
};

function fragmentLabel(id: string): string {
  return FRAGMENTS.find((f) => f.id === id)?.label || id;
}

function authHeaders(secret: string): HeadersInit {
  return { Authorization: `Bearer ${secret}` };
}

function errorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const obj = payload as Record<string, unknown>;
  const detail = obj.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const d = detail as Record<string, unknown>;
    if (typeof d.message === "string") return d.message;
    if (typeof d.code === "string") return d.code;
  }
  return fallback;
}

function fmt(n: number | undefined): string {
  if (typeof n !== "number" || Number.isNaN(n)) return "—";
  return n.toFixed(3);
}

export function WritingSignalsLabPage() {
  const { pathname } = useLocation();
  const secret = secretFromOpsPath(pathname);
  const fileRef = useRef<HTMLInputElement>(null);

  const [exemplars, setExemplars] = useState<ExemplarItem[]>([]);
  const [loadError, setLoadError] = useState("");
  const [filter, setFilter] = useState<string>("all");
  const [fragment, setFragment] = useState("dialogue_dyad");
  const [text, setText] = useState("");
  const [slug, setSlug] = useState<string | null>(null);
  const [scoring, setScoring] = useState(false);
  const [scoreError, setScoreError] = useState("");
  const [result, setResult] = useState<ScoreResponse | null>(null);
  const [platformPrefs, setPlatformPrefs] = useState<LabPrefs | null>(null);
  const [trialPrefs, setTrialPrefs] = useState<LabPrefs | null>(null);

  const loadExemplars = useCallback(async () => {
    if (!secret) return;
    setLoadError("");
    try {
      const res = await fetch("/api/v1/ops/writing/exemplars", {
        headers: authHeaders(secret),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        setLoadError(errorMessage(payload, `加载范文失败 (${res.status})`));
        return;
      }
      const rows = Array.isArray(payload.exemplars) ? payload.exemplars : [];
      setExemplars(rows as ExemplarItem[]);
      const cloned = clonePrefs(payload.prefs);
      if (cloned) {
        setPlatformPrefs(cloned);
        setTrialPrefs(clonePrefs(payload.prefs));
      }
    } catch {
      setLoadError("无法连接 API");
    }
  }, [secret]);

  useEffect(() => {
    void loadExemplars();
  }, [loadExemplars]);

  const visible = useMemo(() => {
    if (filter === "all") return exemplars;
    return exemplars.filter((item) => item.fragment === filter);
  }, [exemplars, filter]);

  const score = useCallback(
    async (opts?: { text?: string; fragment?: string; slug?: string | null }) => {
      if (!secret) return;
      const nextText = opts?.text ?? text;
      const nextFragment = opts?.fragment ?? fragment;
      const nextSlug = opts && "slug" in opts ? opts.slug ?? null : slug;
      if (!nextSlug && !nextText.trim()) {
        setScoreError("请选择范文，或粘贴 / 上传文章");
        return;
      }
      setScoring(true);
      setScoreError("");
      try {
        const body: Record<string, unknown> = { fragment: nextFragment };
        if (nextSlug) body.slug = nextSlug;
        if (nextText.trim()) body.text = nextText;
        if (trialPrefs) body.prefs = trialPrefs;
        const res = await fetch("/api/v1/ops/writing/score", {
          method: "POST",
          headers: { ...authHeaders(secret), "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) {
          setScoreError(errorMessage(payload, `评分失败 (${res.status})`));
          return;
        }
        setResult(payload as ScoreResponse);
      } catch {
        setScoreError("无法连接 API");
      } finally {
        setScoring(false);
      }
    },
    [secret, text, fragment, slug, trialPrefs],
  );

  const pickExemplar = (item: ExemplarItem) => {
    setFragment(item.fragment);
    setText(item.text);
    setSlug(item.slug);
    setFilter(item.fragment);
    void score({ text: item.text, fragment: item.fragment, slug: item.slug });
  };

  const onUpload = async (file: File | undefined) => {
    if (!file) return;
    const raw = await file.text();
    setSlug(null);
    setText(raw);
    setResult(null);
    void score({ text: raw, slug: null });
  };

  const signals = result?.writing_signals;
  const net = signals?.net_signal;

  return (
    <OpsShell
      secret={secret}
      title="写作评分"
      subtitle="范文或自备正文试跑启发式。左侧点范文；下面的权重/奖惩只在本页试跑，觉得好再写进平台默认。不写评测库、不进用户设置。"
    >
      {loadError ? (
        <p className="mb-3 text-sm text-destructive">{loadError}</p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(16rem,20rem)_minmax(0,1fr)]">
        <aside className="rounded-lg border border-border bg-card">
          <div className="border-b border-border px-3 py-2">
            <p className="text-xs font-medium text-foreground">平台范文</p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              点击即评分。学节奏与质地，不搬情节。
            </p>
            <div className="mt-2 flex flex-wrap gap-1">
              <button
                type="button"
                className={`rounded-md border px-2 py-0.5 text-[11px] ${
                  filter === "all"
                    ? "border-foreground/40 bg-foreground/5 font-medium"
                    : "border-border hover:bg-muted"
                }`}
                onClick={() => setFilter("all")}
              >
                全部
              </button>
              {FRAGMENTS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  className={`rounded-md border px-2 py-0.5 text-[11px] ${
                    filter === f.id
                      ? "border-foreground/40 bg-foreground/5 font-medium"
                      : "border-border hover:bg-muted"
                  }`}
                  onClick={() => setFilter(f.id)}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>
          <ul className="max-h-[70vh] overflow-y-auto p-1">
            {visible.map((item) => {
              const active = slug === item.slug && fragment === item.fragment;
              return (
                <li key={`${item.fragment}:${item.slug}`}>
                  <button
                    type="button"
                    onClick={() => pickExemplar(item)}
                    className={`w-full rounded-md px-2 py-1.5 text-left text-xs hover:bg-muted ${
                      active ? "bg-foreground/5" : ""
                    }`}
                  >
                    <div className="text-[11px] text-muted-foreground">
                      {fragmentLabel(item.fragment)}
                    </div>
                    <div className="truncate text-foreground">
                      {item.author}《{item.work}》
                      {item.beat ? `·${item.beat}` : ""}
                    </div>
                  </button>
                </li>
              );
            })}
            {!visible.length ? (
              <li className="px-2 py-6 text-center text-xs text-muted-foreground">
                {exemplars.length ? "该类型暂无范文" : "范文列表为空"}
              </li>
            ) : null}
          </ul>
        </aside>

        <div className="space-y-3">
          {trialPrefs ? (
            <details className="rounded-lg border border-border bg-card p-3">
              <summary className="cursor-pointer text-xs font-medium">
                试跑参数（权重 + 奖惩 · 不进用户设置）
              </summary>
              <p className="mt-2 text-[11px] text-muted-foreground">
                调的是当前申报类型「{fragmentLabel(fragment)}」。试完觉得好，再把数字写进平台默认。
              </p>
              <div className="mt-3 space-y-2">
                {DIMENSIONS.map((d) => {
                  const v = Math.round((trialPrefs.fragment_weights[fragment]?.[d.id] ?? 0) * 100);
                  return (
                    <label key={d.id} className="block text-xs">
                      <div className="mb-0.5 flex justify-between">
                        <span>{d.label}</span>
                        <span className="tabular-nums text-muted-foreground">{v}%</span>
                      </div>
                      <input
                        type="range"
                        min={5}
                        max={60}
                        value={v}
                        className="w-full"
                        onChange={(e) => {
                          const next = Number(e.target.value);
                          setTrialPrefs((prev) => {
                            if (!prev) return prev;
                            const row = { ...(prev.fragment_weights[fragment] ?? {}) };
                            row[d.id] = next / 100;
                            return {
                              ...prev,
                              fragment_weights: { ...prev.fragment_weights, [fragment]: row },
                            };
                          });
                        }}
                      />
                    </label>
                  );
                })}
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div>
                  <p className="mb-1 text-[11px] font-medium text-muted-foreground">惩罚</p>
                  {PENALTY_SIGNALS.map((s) => (
                    <label key={s.id} className="flex items-center gap-2 text-xs">
                      <input
                        type="checkbox"
                        checked={Math.abs(Number(trialPrefs.signal_penalties[fragment]?.[s.id] ?? 0)) > 0.001}
                        onChange={() => {
                          const on = Math.abs(Number(trialPrefs.signal_penalties[fragment]?.[s.id] ?? 0)) <= 0.001;
                          setTrialPrefs((prev) => {
                            if (!prev) return prev;
                            const row = { ...(prev.signal_penalties[fragment] ?? {}) };
                            row[s.id] = on ? s.magnitude : 0;
                            return {
                              ...prev,
                              signal_penalties: { ...prev.signal_penalties, [fragment]: row },
                            };
                          });
                        }}
                      />
                      {s.label}
                    </label>
                  ))}
                </div>
                <div>
                  <p className="mb-1 text-[11px] font-medium text-muted-foreground">奖励</p>
                  {REWARD_SIGNALS.map((s) => (
                    <label key={s.id} className="flex items-center gap-2 text-xs">
                      <input
                        type="checkbox"
                        checked={Math.abs(Number(trialPrefs.signal_rewards[fragment]?.[s.id] ?? 0)) > 0.001}
                        onChange={() => {
                          const on = Math.abs(Number(trialPrefs.signal_rewards[fragment]?.[s.id] ?? 0)) <= 0.001;
                          setTrialPrefs((prev) => {
                            if (!prev) return prev;
                            const row = { ...(prev.signal_rewards[fragment] ?? {}) };
                            row[s.id] = on ? s.magnitude : 0;
                            return {
                              ...prev,
                              signal_rewards: { ...prev.signal_rewards, [fragment]: row },
                            };
                          });
                        }}
                      />
                      {s.label}
                    </label>
                  ))}
                </div>
              </div>
              {platformPrefs ? (
                <button
                  type="button"
                  className="mt-3 rounded-md border border-border px-2 py-1 text-[11px] hover:bg-muted"
                  onClick={() => setTrialPrefs(clonePrefs(platformPrefs))}
                >
                  恢复平台默认参数
                </button>
              ) : null}
            </details>
          ) : null}

          <div className="rounded-lg border border-border bg-card p-3">
            <div className="flex flex-wrap items-end gap-2">
              <label className="text-xs">
                <span className="mb-1 block text-muted-foreground">申报片段类型</span>
                <select
                  className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  value={fragment}
                  onChange={(e) => setFragment(e.target.value)}
                >
                  {FRAGMENTS.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.label}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50"
                onClick={() => void score()}
                disabled={scoring}
              >
                {scoring ? "评分中…" : "评分"}
              </button>
              <button
                type="button"
                className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-muted"
                onClick={() => fileRef.current?.click()}
              >
                上传 .txt / .md
              </button>
              <input
                ref={fileRef}
                type="file"
                accept=".txt,.md,.markdown,text/plain"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  void onUpload(file);
                }}
              />
              {slug ? (
                <span className="text-[11px] text-muted-foreground">来源：范文 {slug}</span>
              ) : text.trim() ? (
                <span className="text-[11px] text-muted-foreground">来源：自备正文</span>
              ) : null}
            </div>
            <textarea
              className="mt-3 min-h-[14rem] w-full rounded-md border border-border bg-background px-3 py-2 font-serif text-sm leading-relaxed"
              placeholder="粘贴待测正文，或从左侧点一篇范文。"
              value={text}
              onChange={(e) => {
                setSlug(null);
                setText(e.target.value);
              }}
            />
            {scoreError ? (
              <p className="mt-2 text-xs text-destructive">{scoreError}</p>
            ) : null}
          </div>

          {signals ? (
            <div className="space-y-3 rounded-lg border border-border bg-card p-3">
              <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <p className="text-2xl font-semibold tabular-nums">
                  net {fmt(net)}
                </p>
                <p className="text-sm text-muted-foreground">
                  composite {fmt(signals.composite)}
                  {typeof signals.exemplar_fit?.score === "number"
                    ? ` · 原型贴近 ${fmt(signals.exemplar_fit.score)}`
                    : null}
                </p>
                {result?.persisted ? (
                  <span className="text-[11px] text-destructive">已写库（不应发生）</span>
                ) : (
                  <span className="text-[11px] text-muted-foreground">未写库</span>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                申报 {fragmentLabel(signals.fragment?.declared || fragment)}
                {" · "}
                检测 {fragmentLabel(signals.fragment?.detected || "—")}
                {signals.fragment?.mismatch ? " · 类型不一致" : ""}
                {signals.exemplar_fit?.nearest?.author
                  ? ` · 最近样本 ${signals.exemplar_fit.nearest.author}《${signals.exemplar_fit.nearest.work || ""}》`
                  : ""}
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <p className="mb-1 text-[11px] font-medium text-muted-foreground">维度</p>
                  <ul className="space-y-1">
                    {DIMENSIONS.map((d) => {
                      const v = Number(signals.dimensions?.[d.id] ?? 0);
                      return (
                        <li key={d.id} className="text-xs">
                          <div className="flex justify-between gap-2">
                            <span>{d.label}</span>
                            <span className="tabular-nums text-muted-foreground">{fmt(v)}</span>
                          </div>
                          <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-muted">
                            <div
                              className="h-full rounded-full bg-foreground/60"
                              style={{ width: `${Math.max(0, Math.min(100, v * 100))}%` }}
                            />
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </div>
                <div className="space-y-2">
                  <div>
                    <p className="mb-1 text-[11px] font-medium text-muted-foreground">奖励</p>
                    {(signals.rewards || []).length ? (
                      <ul className="space-y-1">
                        {(signals.rewards || []).map((r) => (
                          <li key={r.key} className="text-xs">
                            <span className="font-mono">{r.key}</span>
                            <span className="text-muted-foreground">
                              {" "}
                              {r.delta != null && r.delta > 0 ? "+" : ""}
                              {fmt(r.delta)} {r.hint || ""}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-xs text-muted-foreground">无</p>
                    )}
                  </div>
                  <div>
                    <p className="mb-1 text-[11px] font-medium text-muted-foreground">惩罚</p>
                    {(signals.penalties || []).length ? (
                      <ul className="space-y-1">
                        {(signals.penalties || []).map((p) => (
                          <li key={p.key} className="text-xs">
                            <span className="font-mono">{p.key}</span>
                            <span className="text-muted-foreground">
                              {" "}
                              {fmt(p.delta)} {p.hint || ""}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-xs text-muted-foreground">无</p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              点左侧范文，或在框内贴文后点「评分」。
            </p>
          )}
        </div>
      </div>
    </OpsShell>
  );
}
