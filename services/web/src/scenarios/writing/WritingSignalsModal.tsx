import { useCallback, useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import {
  fetchWorkspaceFile,
  saveWorkspaceFile,
} from "../../shared/api/client";
import { Button } from "../../components/ui/button";

export type WorkModeChoice = "auto" | "literary" | "web_serial";
export type BookScopeChoice = "auto" | "short" | "single" | "long";

const PREFS_PATH = "writing_prefs.json";

const SCOPE_CHOICES: { id: BookScopeChoice; label: string; hint: string }[] = [
  { id: "auto", label: "自动", hint: "按用户句推断" },
  { id: "short", label: "短篇", hint: "一篇收束的微型弧" },
  { id: "single", label: "单篇", hint: "一篇完整小故事" },
  { id: "long", label: "长篇", hint: "一次一章，海先藏着" },
];

const MODE_CHOICES: { id: WorkModeChoice; label: string; hint: string }[] = [
  { id: "auto", label: "自动", hint: "按用户句推断" },
  { id: "literary", label: "经典文学", hint: "句味·人物·环境" },
  { id: "web_serial", label: "连载网文", hint: "长纲·强钩·台阶" },
];

const STYLES: { id: string; label: string; blurb: string }[] = [
  { id: "plot_progress", label: "情节推进", blurb: "把一件事在场面里往前推" },
  { id: "worldview_texture", label: "环境质地", blurb: "规矩、地方、设定可感" },
  { id: "climax_beat", label: "高潮", blurb: "一件麻烦顶满再落下" },
  { id: "battle_action", label: "动作", blurb: "来回有力，不是电报体" },
  { id: "dialogue_dyad", label: "对白", blurb: "长短不齐，有人物距离" },
  { id: "mixed", label: "综合", blurb: "人物/情节/环境掺着写" },
];

/** Platform defaults — not all 100%; mode emphasizes different axes. */
const DEFAULT_GAINS: Record<Exclude<WorkModeChoice, "auto">, Record<string, number>> = {
  literary: {
    dialogue_dyad: 0.85,
    worldview_texture: 0.8,
    mixed: 0.7,
    plot_progress: 0.55,
    climax_beat: 0.5,
    battle_action: 0.35,
  },
  web_serial: {
    plot_progress: 0.85,
    climax_beat: 0.75,
    battle_action: 0.7,
    mixed: 0.7,
    worldview_texture: 0.55,
    dialogue_dyad: 0.5,
  },
};

type Gains = Record<string, number>;

type StoredPrefs = {
  work_mode?: { source?: string; mode?: string };
  book_scope?: { source?: string; scope?: string };
  style_gains?: Record<string, number>;
};

function modeForDefaults(choice: WorkModeChoice): "literary" | "web_serial" {
  return choice === "web_serial" ? "web_serial" : "literary";
}

function fullDefaults(choice: WorkModeChoice): Gains {
  return { ...DEFAULT_GAINS[modeForDefaults(choice)] };
}

function parsePrefs(raw: string | undefined): {
  choice: WorkModeChoice;
  scope: BookScopeChoice;
  gains: Gains;
} {
  const fallbackChoice: WorkModeChoice = "auto";
  const fallbackScope: BookScopeChoice = "auto";
  const fallbackGains = fullDefaults(fallbackChoice);
  if (!raw?.trim()) {
    return { choice: fallbackChoice, scope: fallbackScope, gains: fallbackGains };
  }
  try {
    const data = JSON.parse(raw) as StoredPrefs;
    let choice: WorkModeChoice = "auto";
    if (
      data.work_mode?.source === "user" &&
      (data.work_mode.mode === "literary" || data.work_mode.mode === "web_serial")
    ) {
      choice = data.work_mode.mode;
    }
    let scope: BookScopeChoice = "auto";
    if (
      data.book_scope?.source === "user" &&
      (data.book_scope.scope === "short" ||
        data.book_scope.scope === "single" ||
        data.book_scope.scope === "long")
    ) {
      scope = data.book_scope.scope;
    }
    const base = fullDefaults(choice);
    const gains: Gains = { ...base };
    if (data.style_gains && typeof data.style_gains === "object") {
      for (const s of STYLES) {
        const v = Number(data.style_gains[s.id]);
        if (Number.isFinite(v)) gains[s.id] = Math.max(0, Math.min(1, v));
      }
    }
    return { choice, scope, gains };
  } catch {
    return { choice: fallbackChoice, scope: fallbackScope, gains: fallbackGains };
  }
}

function serializePrefs(
  choice: WorkModeChoice,
  gains: Gains,
  scope: BookScopeChoice,
): string {
  const work_mode =
    choice === "auto"
      ? { source: "auto", mode: "literary" }
      : { source: "user", mode: choice };
  const book_scope =
    scope === "auto"
      ? { source: "auto", scope: "single" }
      : { source: "user", scope };
  const style_gains = Object.fromEntries(
    STYLES.map((s) => [s.id, Math.round((gains[s.id] ?? 0.7) * 100) / 100]),
  );
  return `${JSON.stringify({ work_mode, book_scope, style_gains }, null, 2)}\n`;
}

type Props = {
  open: boolean;
  onClose: () => void;
};

export function WritingSignalsModal({ open, onClose }: Props) {
  const [choice, setChoice] = useState<WorkModeChoice>("auto");
  const [scope, setScope] = useState<BookScopeChoice>("auto");
  const [gains, setGains] = useState<Gains>(() => fullDefaults("auto"));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      try {
        const file = await fetchWorkspaceFile(PREFS_PATH);
        if (cancelled) return;
        const parsed = parsePrefs(file.content);
        setChoice(parsed.choice);
        setScope(parsed.scope);
        setGains(parsed.gains);
        setDirty(false);
        setMsg(null);
      } catch {
        if (cancelled) return;
        setChoice("auto");
        setScope("auto");
        setGains(fullDefaults("auto"));
        setDirty(false);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  const effectiveMode = useMemo(() => modeForDefaults(choice), [choice]);

  const setGain = (id: string, pct: number) => {
    const nextVal = Math.max(0, Math.min(100, pct)) / 100;
    setGains((prev) => ({ ...prev, [id]: nextVal }));
    setDirty(true);
  };

  const applyModeDefaults = () => {
    setGains(fullDefaults(choice));
    setDirty(true);
    setMsg(`已套用${choice === "web_serial" ? "连载网文" : "经典文学"}默认贴近（未满档）`);
  };

  const save = useCallback(async () => {
    setBusy(true);
    setMsg(null);
    try {
      await saveWorkspaceFile(PREFS_PATH, serializePrefs(choice, gains, scope));
      setDirty(false);
      setMsg("已保存尺度与模式。奖励不进 net；同轮只修 L0。编辑札记在下一章。");
    } catch (e) {
      setMsg(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }, [choice, gains, scope]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div
        className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-border bg-background shadow-xl"
        role="dialog"
        aria-labelledby="writing-signals-title"
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div>
            <h2 id="writing-signals-title" className="text-base font-semibold">
              写作信号
            </h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              钉作品尺度与模式。L1 奖励只观测，net 低不再同轮修补；同轮只修过程
              L0。不够光滑的章会进下一章的编辑札记。存于{" "}
              <code className="text-[10px]">{PREFS_PATH}</code>
              ，账户设置页无滑条。
            </p>
          </div>
          <button
            type="button"
            className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={onClose}
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4">
          {!loaded ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : (
            <>
              <section>
                <h3 className="text-sm font-medium">作品尺度</h3>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  短篇/单篇一篇收束；长篇一次一章。钉死后「写一篇玄幻」仍按长篇开写；句里写明短篇/长篇仍优先。
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {SCOPE_CHOICES.map((c) => {
                    const active = scope === c.id;
                    return (
                      <button
                        key={c.id}
                        type="button"
                        title={c.hint}
                        disabled={busy}
                        onClick={() => {
                          setScope(c.id);
                          setDirty(true);
                        }}
                        className={`rounded-md border px-3 py-1.5 text-xs transition-colors disabled:opacity-50 ${
                          active
                            ? "border-primary bg-primary/20 text-primary"
                            : "border-border bg-card/50 text-muted-foreground hover:border-primary/40 hover:text-foreground"
                        }`}
                      >
                        {c.label}
                      </button>
                    );
                  })}
                </div>
              </section>

              <section>
                <h3 className="text-sm font-medium">作品模式</h3>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  决定维度权重与默认声口。钉死后不跟用户句自动变。
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {MODE_CHOICES.map((c) => {
                    const active = choice === c.id;
                    return (
                      <button
                        key={c.id}
                        type="button"
                        title={c.hint}
                        disabled={busy}
                        onClick={() => {
                          setChoice(c.id);
                          setGains(fullDefaults(c.id));
                          setDirty(true);
                        }}
                        className={`rounded-md border px-3 py-1.5 text-xs transition-colors disabled:opacity-50 ${
                          active
                            ? "border-primary bg-primary/20 text-primary"
                            : "border-border bg-card/50 text-muted-foreground hover:border-primary/40 hover:text-foreground"
                        }`}
                      >
                        {c.label}
                      </button>
                    );
                  })}
                </div>
                <p className="mt-1.5 text-[10px] text-muted-foreground">
                  当前有效轴：{effectiveMode === "web_serial" ? "连载网文" : "经典文学"}
                  {choice === "auto" ? "（自动推断时按用户句切换）" : "（已钉死）"}
                </p>
              </section>

              <section>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h3 className="text-sm font-medium">奖惩贴近</h3>
                    <p className="mt-0.5 text-[11px] text-muted-foreground">
                      只缩放惩罚观测强度，奖励不进 net。不是「低于 0.50 就同轮打磨」的开关。
                    </p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={applyModeDefaults}
                  >
                    恢复本模式默认
                  </Button>
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {STYLES.map((s) => {
                    const gain = gains[s.id] ?? 0.7;
                    const pct = Math.round(gain * 100);
                    return (
                      <div
                        key={s.id}
                        className={`rounded-xl border p-3 ${
                          pct > 0
                            ? "border-primary/40 bg-primary/10"
                            : "border-border bg-card/40"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-sm font-medium">{s.label}</p>
                          <span className="tabular-nums text-[11px] text-muted-foreground">
                            {pct}%
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">{s.blurb}</p>
                        <label className="mt-2 block">
                          <div className="mb-1 flex justify-between text-[11px] text-muted-foreground">
                            <span>关</span>
                            <span>满</span>
                          </div>
                          <input
                            type="range"
                            min={0}
                            max={100}
                            step={5}
                            value={pct}
                            className="h-2 w-full accent-primary"
                            aria-label={`${s.label}贴近 ${pct}%`}
                            disabled={busy}
                            onChange={(e) => setGain(s.id, Number(e.target.value))}
                          />
                        </label>
                      </div>
                    );
                  })}
                </div>
              </section>
            </>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-3">
          <p className="text-xs text-muted-foreground">{msg ?? " "}</p>
          <div className="flex gap-2">
            <Button type="button" variant="outline" size="sm" onClick={onClose}>
              关闭
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!dirty || busy || !loaded}
              onClick={() => void save()}
            >
              保存
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
