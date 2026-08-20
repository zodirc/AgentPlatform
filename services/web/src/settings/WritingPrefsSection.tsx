import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchWritingPrefs,
  resetWritingPrefs,
  updateWritingPrefs,
  type WritingPrefs,
} from "../shared/api/client";

const STYLES: { id: string; label: string; blurb: string }[] = [
  { id: "plot_progress", label: "情节推进", blurb: "把一件事在场面里往前推" },
  { id: "worldview_texture", label: "日子与规矩", blurb: "把地方、价钱、谁管这块地写清楚" },
  { id: "climax_beat", label: "高潮", blurb: "一件麻烦顶满，再允许它落下" },
  { id: "battle_action", label: "动作", blurb: "来回有力，不是电报体砍杀" },
  { id: "dialogue_dyad", label: "对白", blurb: "长短不齐，问完可以答不上来" },
  { id: "mixed", label: "平紧落", blurb: "过日子、加压、收束掺着写" },
];

const PENALTY_ON: Record<string, number> = {
  hinge_dense: -0.12,
  staccato_uniform: -0.15,
  opening_institution: -0.1,
  lore_dump: -0.1,
  length_short: -0.08,
  meta_knowing_high: -0.06,
  glue_heavy: -0.05,
  fragment_mismatch: -0.1,
};

const REWARD_ON: Record<string, number> = {
  scene_ratio_high: 0.08,
  dialogue_rhythm_varied: 0.1,
  exemplar_alignment_high: 0.12,
  outline_duty_match: 0.1,
  character_card_action: 0.08,
};

type SignalTable = Record<string, Record<string, number>>;
type Gains = Record<string, number>;

function emptyZero(keys: string[]): SignalTable {
  const row = Object.fromEntries(keys.map((k) => [k, 0]));
  return Object.fromEntries(STYLES.map((s) => [s.id, { ...row }]));
}

function nestSignals(raw: unknown, keys: string[]): SignalTable {
  const fallback = emptyZero(keys);
  if (!raw || typeof raw !== "object") return fallback;
  const obj = raw as Record<string, unknown>;
  const first = Object.values(obj)[0];
  if (first && typeof first === "object" && !Array.isArray(first)) {
    const out = emptyZero(keys);
    for (const s of STYLES) {
      const row = obj[s.id];
      if (row && typeof row === "object") {
        out[s.id] = { ...out[s.id], ...(row as Record<string, number>) };
      }
    }
    return out;
  }
  return Object.fromEntries(STYLES.map((s) => [s.id, { ...fallback[s.id], ...(obj as Record<string, number>) }]));
}

function scaleRow(template: Record<string, number>, gain: number): Record<string, number> {
  const g = Math.max(0, Math.min(1, gain));
  return Object.fromEntries(Object.entries(template).map(([k, v]) => [k, Math.round(v * g * 10000) / 10000]));
}

function tablesFromGains(gains: Gains): { penalties: SignalTable; rewards: SignalTable } {
  const penalties: SignalTable = {};
  const rewards: SignalTable = {};
  for (const s of STYLES) {
    const g = gains[s.id] ?? 1;
    penalties[s.id] = scaleRow(PENALTY_ON, g);
    rewards[s.id] = scaleRow(REWARD_ON, g);
  }
  return { penalties, rewards };
}

function inferGains(penalties: SignalTable, rewards: SignalTable): Gains {
  const out: Gains = {};
  for (const s of STYLES) {
    const ratios: number[] = [];
    for (const [key, plat] of Object.entries(PENALTY_ON)) {
      if (Math.abs(plat) < 0.001) continue;
      ratios.push(Math.abs(Number(penalties[s.id]?.[key] ?? 0) / plat));
    }
    for (const [key, plat] of Object.entries(REWARD_ON)) {
      if (Math.abs(plat) < 0.001) continue;
      ratios.push(Math.abs(Number(rewards[s.id]?.[key] ?? 0) / plat));
    }
    const mean = ratios.length ? ratios.reduce((a, b) => a + b, 0) / ratios.length : 0;
    out[s.id] = Math.max(0, Math.min(1, Math.round(mean * 100) / 100));
  }
  return out;
}

function fullGains(): Gains {
  return Object.fromEntries(STYLES.map((s) => [s.id, 1]));
}

export function WritingPrefsSection() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["writing-prefs"],
    queryFn: fetchWritingPrefs,
    retry: false,
  });

  const [gains, setGains] = useState<Gains>(fullGains);
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const hydrate = useCallback((prefs: WritingPrefs) => {
    const penalties = nestSignals(prefs.signal_penalties, Object.keys(PENALTY_ON));
    const rewards = nestSignals(prefs.signal_rewards, Object.keys(REWARD_ON));
    const next = inferGains(penalties, rewards);
    if (STYLES.every((s) => (next[s.id] ?? 0) < 0.05)) {
      setGains(fullGains());
    } else {
      setGains(next);
    }
    setDirty(false);
  }, []);

  useEffect(() => {
    if (q.data) hydrate(q.data);
  }, [q.data, hydrate]);

  const saveMut = useMutation({
    mutationFn: () => {
      const { penalties, rewards } = tablesFromGains(gains);
      const allFull = STYLES.every((s) => (gains[s.id] ?? 0) >= 0.995);
      return updateWritingPrefs({
        preset_label: allFull ? "balanced" : "custom",
        signal_penalties: penalties,
        signal_rewards: rewards,
      });
    },
    onSuccess: (data) => {
      hydrate(data);
      qc.setQueryData(["writing-prefs"], data);
      setMsg("已保存。成稿会按你拉的贴近强弱来打分。");
    },
    onError: (e: Error) => setMsg(`保存失败：${e.message}`),
  });

  const resetMut = useMutation({
    mutationFn: resetWritingPrefs,
    onSuccess: (data) => {
      hydrate(data);
      qc.setQueryData(["writing-prefs"], data);
      setMsg("已恢复为全部贴近。");
    },
    onError: (e: Error) => setMsg(`重置失败：${e.message}`),
  });

  const setGain = (id: string, pct: number) => {
    const nextVal = Math.max(0, Math.min(100, pct)) / 100;
    setGains((prev) => {
      const next = { ...prev, [id]: nextVal };
      if (STYLES.every((s) => (next[s.id] ?? 0) < 0.05)) return prev;
      return next;
    });
    setDirty(true);
  };

  if (q.isLoading) {
    return <p className="text-sm text-muted-foreground">加载中…</p>;
  }

  if (q.isError) {
    return (
      <div className="space-y-3">
        <h2 className="text-lg font-semibold">写作风格</h2>
        <p className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
          暂无法加载。请先登录工作台账号。
        </p>
        <Link
          to="/writing"
          className="inline-block rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-muted"
        >
          去登录
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">写作风格</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          拖动进度条，决定成稿更贴近哪一种写法。学节奏和质地，不要搬范文情节。维度怎么加权仍由平台统一。
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {STYLES.map((s) => {
          const gain = gains[s.id] ?? 1;
          const pct = Math.round(gain * 100);
          const exemplars = q.data?.exemplars?.[s.id] ?? [];
          return (
            <div
              key={s.id}
              className={`rounded-xl border p-4 ${
                pct > 0 ? "border-primary/40 bg-primary/10" : "border-border bg-card/40"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-medium">{s.label}</p>
                <span className="tabular-nums text-[11px] text-muted-foreground">{pct}%</span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{s.blurb}</p>
              {exemplars.length ? (
                <p className="mt-2 text-[11px] text-muted-foreground">
                  {exemplars
                    .slice(0, 2)
                    .map((ex) => `${ex.author}《${ex.work}》`)
                    .join(" · ")}
                </p>
              ) : null}
              <label className="mt-3 block">
                <div className="mb-1 flex justify-between text-[11px] text-muted-foreground">
                  <span>不强调</span>
                  <span>贴近</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={5}
                  value={pct}
                  className="h-2 w-full accent-primary"
                  aria-label={`${s.label}贴近 ${pct}%`}
                  onChange={(e) => setGain(s.id, Number(e.target.value))}
                />
              </label>
            </div>
          );
        })}
      </div>

      {msg ? <p className="text-sm text-muted-foreground">{msg}</p> : null}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="rounded-lg bg-primary px-4 py-2 text-sm disabled:opacity-50"
          disabled={!dirty || saveMut.isPending}
          onClick={() => saveMut.mutate()}
        >
          保存
        </button>
        <button
          type="button"
          className="rounded-lg border border-input px-4 py-2 text-sm text-muted-foreground"
          disabled={resetMut.isPending}
          onClick={() => resetMut.mutate()}
        >
          全部贴近
        </button>
      </div>
    </div>
  );
}
