import { LiveProgress } from "./LiveProgress";
import { scenarioLabelForSuite } from "./presets";
import type {
  ApiStyle,
  CodingTierMeta,
  ContextTier,
  Preset,
  ProviderPreset,
  RetrievalTier,
  SuiteId,
  TargetMeta,
} from "./types";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type LivePaneModel = Record<string, any>;

export function LivePane({ model }: { model: LivePaneModel }) {
  const {
    busy,
    selectedSuites,
    targetEnabled,
    startRun,
    error,
    opsDisplayText,
    profileButtons,
    activeProfileId,
    profileFormOpen,
    setProfileFormOpen,
    applyPreset,
    selectCustomProfile,
    CUSTOM_PROFILE_ID,
    activeProfileLabel,
    activeProfileHint,
    suitesLabelZh,
    displaySuites,
    paramsFromActiveRun,
    codingTier,
    codingNInstances,
    setCodingNInstances,
    retrievalTierLabel,
    displayRetrievalTier,
    contextTierLabel,
    displayContextTier,
    displayParallel,
    BENCH_SCENARIO_GROUPS,
    targetsMeta,
    FALLBACK_SUITE_META,
    markCustomProfile,
    toggleSuite,
    retrievalTier,
    setRetrievalTier,
    contextTier,
    setContextTier,
    l1Parallel,
    setL1Parallel,
    codingTierMeta,
    setCodingTier,
    caps,
    needsLiveModel,
    modelProvider,
    applyProviderPreset,
    PROVIDER_PRESETS,
    modelApiStyle,
    setModelApiStyle,
    modelName,
    setModelName,
    modelBaseUrl,
    setModelBaseUrl,
    apiKeySaveFlash,
    apiKeyStored,
    apiKeyEditing,
    setApiKeyEditing,
    apiKeyDirty,
    storedApiKey,
    modelApiKey,
    setModelApiKey,
    clearApiKey,
    saveApiKey,
    modelContextWindow,
    setModelContextWindow,
    probeBusy,
    probeModel,
    probeMessage,
    probeOk,
    lastFinishedLiveId,
    shortId,
    historyDeepLinkDoneRef,
    setPagePane,
    navigate,
    opsOfficialPath,
    secret,
    setLastFinishedLiveId,
    selectedId,
    liveRun,
    runSuitesLabel,
  } = model;
  // Keep type imports referenced for editors; casts use these names in JSX.
  type _Keep = ApiStyle | ContextTier | RetrievalTier;
  void 0 as unknown as _Keep;

  return (
        <>
          {/* Process legend */}
          <section className="mb-4 rounded-xl border border-border bg-muted/30 px-4 py-3 text-xs">
            <p className="font-semibold text-foreground">
              你始终该知道在干嘛（每个套件都是这三步）
            </p>
            <ol className="mt-2 grid gap-2 sm:grid-cols-3">
              <li className="rounded-lg border border-border bg-background/80 px-3 py-2">
                <span className="font-medium">① 拉取 Pull</span>
                <p className="mt-0.5 text-muted-foreground">
                  BEIR / LongBench / SWE 题集进缓存；
                  <strong>已有则跳过下载</strong>。慢通常只发生在第一次。
                </p>
              </li>
              <li className="rounded-lg border border-border bg-background/80 px-3 py-2">
                <span className="font-medium">② 评测 Eval</span>
                <p className="mt-0.5 text-muted-foreground">
                  跑检索 / 上下文 / 编码，产出 nDCG、retention、patch 率等指标。
                </p>
              </li>
              <li className="rounded-lg border border-border bg-background/80 px-3 py-2">
                <span className="font-medium">③ 回归 Regress</span>
                <p className="mt-0.5 text-muted-foreground">
                  「指标汇总」页看多次 <strong>completed</strong> 跑分的最高 /
                  平均 / 中位；相对上次 Δ 也在检索日志里。
                </p>
              </li>
            </ol>
            <p className="mt-2 text-muted-foreground">
              首次拉 BEIR 走德国 UKP 源，国内慢可开代理；
              <strong>拉完会缓存</strong>，之后主要是 ②③。
              历史跑次与详情在顶栏「历史」，进入本页默认只看本轮发起。
            </p>
          </section>

          {/* Launch strip */}
          <section className="mb-5 rounded-xl border border-border bg-gradient-to-b from-card/80 to-background p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">发起一次 Bench</h2>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={
                    busy ||
                    Array.from(selectedSuites).filter(targetEnabled).length ===
                      0
                  }
                  onClick={() => void startRun()}
                  className="rounded-md bg-foreground px-4 py-1.5 text-sm text-background disabled:opacity-40"
                >
                  {busy ? "运行中…" : "开始"}
                </button>
                {opsDisplayText(error)?.includes("已有 Bench") ? (
                  <button
                    type="button"
                    onClick={() => void startRun({ force: true })}
                    className="rounded-md border border-border px-3 py-1.5 text-sm"
                  >
                    强制重开
                  </button>
                ) : null}
              </div>
            </div>

            <p className="mt-2 text-[11px] text-muted-foreground">
              点配置档会套用参数并打开下方表单；再点同一档可收起。改任一字段会切到「自定义」——刷新后仍保留（写在本机
              prefs）。
            </p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {profileButtons.map((p: Preset) => {
                const on = activeProfileId === p.id;
                return (
                  <button
                    key={p.id}
                    type="button"
                    disabled={busy}
                    title={p.hint}
                    onClick={() => {
                      if (on && profileFormOpen) {
                        setProfileFormOpen(false);
                        return;
                      }
                      applyPreset(p);
                    }}
                    className={`rounded-full border px-2.5 py-1 text-[11px] disabled:opacity-40 ${
                      on
                        ? "border-foreground/60 bg-foreground text-background"
                        : "border-border hover:bg-muted"
                    }`}
                  >
                    {p.label}
                  </button>
                );
              })}
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  selectCustomProfile();
                  setProfileFormOpen(true);
                }}
                className={`rounded-full border px-2.5 py-1 text-[11px] disabled:opacity-40 ${
                  activeProfileId === CUSTOM_PROFILE_ID
                    ? "border-foreground/60 bg-foreground text-background"
                    : "border-border hover:bg-muted"
                }`}
              >
                自定义
              </button>
            </div>

            {profileFormOpen ? (
              <div className="mt-4 space-y-3 border-t border-border pt-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div>
                    <p className="text-xs font-medium">{activeProfileLabel}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {activeProfileHint}
                    </p>
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    套件 {suitesLabelZh(displaySuites)}
                    {paramsFromActiveRun ? " · 当前活动轮参数" : ""}
                  </p>
                </div>

                <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
                  <div className="rounded-md border border-border bg-muted/20 px-2 py-1.5">
                    <span className="text-muted-foreground">编码档 </span>
                    {codingTier}
                    {codingTier === "custom"
                      ? ` · N=${codingNInstances}`
                      : null}
                  </div>
                  <div className="rounded-md border border-border bg-muted/20 px-2 py-1.5">
                    <span className="text-muted-foreground">检索 </span>
                    {retrievalTierLabel(displayRetrievalTier)}
                  </div>
                  <div className="rounded-md border border-border bg-muted/20 px-2 py-1.5">
                    <span className="text-muted-foreground">上下文 </span>
                    {contextTierLabel(displayContextTier)}
                  </div>
                  <div className="rounded-md border border-border bg-muted/20 px-2 py-1.5">
                    <span className="text-muted-foreground">并行 </span>
                    {displayParallel}
                  </div>
                </div>

                <div>
                  <p className="mb-1.5 text-[11px] font-medium text-muted-foreground">
                    套件（按场景）
                  </p>
                  <div className="space-y-3">
                    {BENCH_SCENARIO_GROUPS.map((group: {
                      id: string;
                      label: string;
                      hint: string;
                      suiteIds: readonly SuiteId[];
                    }) => {
                      const groupTargets = group.suiteIds
                        .map(
                          (id: SuiteId) =>
                            targetsMeta.find((t: TargetMeta) => t.id === id) ||
                            FALLBACK_SUITE_META[id],
                        )
                        .filter(Boolean);
                      if (groupTargets.length === 0) return null;
                      return (
                        <div key={group.id}>
                          <div className="mb-1.5 flex flex-wrap items-baseline gap-2">
                            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                              {group.label}
                            </h3>
                            <span className="text-[10px] text-muted-foreground">
                              {group.hint}
                            </span>
                          </div>
                          {group.suiteIds.length === 0 ? (
                            <p className="rounded-lg border border-dashed border-border bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground">
                              尚无挂接套件。
                            </p>
                          ) : (
                            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                              {groupTargets.map((t: TargetMeta) => {
                                const id = t.id;
                                const on = selectedSuites.has(id);
                                const enabled = targetEnabled(id);
                                return (
                                  <button
                                    key={id}
                                    type="button"
                                    disabled={busy || !enabled}
                                    onClick={() => toggleSuite(id)}
                                    className={`rounded-lg border px-3 py-2 text-left text-xs transition-colors disabled:opacity-40 ${
                                      on && enabled
                                        ? "border-foreground/50 bg-foreground/5"
                                        : "border-border hover:bg-muted/50"
                                    }`}
                                  >
                                    <div className="flex items-center justify-between gap-2">
                                      <span className="font-medium">
                                        {t.label}
                                      </span>
                                      <span
                                        className={`h-2 w-2 rounded-full ${on && enabled ? "bg-foreground" : "bg-border"}`}
                                      />
                                    </div>
                                    <p className="mt-1 text-[11px] leading-snug text-muted-foreground">
                                      {t.description}
                                    </p>
                                    <p className="mt-1 text-[10px] text-muted-foreground/80">
                                      场景 · {scenarioLabelForSuite(id)}
                                    </p>
                                  </button>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3">
                  <label className="grid gap-1">
                    <span className="text-[11px] text-muted-foreground">
                      检索档位（qrels/集）
                    </span>
                    <select
                      value={retrievalTier}
                      disabled={busy}
                      onChange={(e) => {
                        markCustomProfile();
                        setRetrievalTier(e.target.value as RetrievalTier);
                      }}
                      className="rounded border border-border bg-background px-1.5 py-1"
                    >
                      <option value="full">全量 qrels (~1.3k)</option>
                      <option value="50">50 q/集</option>
                      <option value="20">20 q/集</option>
                      <option value="10">10 q/集</option>
                      <option value="5">5 q/集</option>
                    </select>
                  </label>
                  <label className="grid gap-1">
                    <span className="text-[11px] text-muted-foreground">
                      上下文档位（样本/任务）
                    </span>
                    <select
                      value={contextTier}
                      disabled={busy}
                      onChange={(e) => {
                        markCustomProfile();
                        setContextTier(e.target.value as ContextTier);
                      }}
                      className="rounded border border-border bg-background px-1.5 py-1"
                    >
                      <option value="full">全量</option>
                      <option value="40">40</option>
                      <option value="20">20</option>
                      <option value="10">10</option>
                      <option value="5">5</option>
                    </select>
                  </label>
                  <label className="grid gap-1">
                    <span className="text-[11px] text-muted-foreground">
                      L1 并行
                    </span>
                    <select
                      value={String(l1Parallel)}
                      disabled={busy}
                      onChange={(e) => {
                        markCustomProfile();
                        setL1Parallel(Number(e.target.value) || 1);
                      }}
                      className="rounded border border-border bg-background px-1.5 py-1"
                    >
                      {[1, 2, 3, 4].map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </label>
                  {selectedSuites.has("coding") ? (
                    <>
                      <label className="grid gap-1">
                        <span className="text-[11px] text-muted-foreground">
                          编码档位
                        </span>
                        <select
                          value={codingTier}
                          disabled={busy}
                          onChange={(e) => {
                            markCustomProfile();
                            setCodingTier(e.target.value);
                          }}
                          className="rounded border border-border bg-background px-1.5 py-1"
                        >
                          {(codingTierMeta || []).map((t: CodingTierMeta) => (
                            <option key={t.id} value={t.id}>
                              {t.id}
                            </option>
                          ))}
                        </select>
                      </label>
                      {codingTier === "custom" ? (
                        <label className="grid gap-1">
                          <span className="text-[11px] text-muted-foreground">
                            自定义 N
                          </span>
                          <input
                            type="number"
                            min={3}
                            max={300}
                            value={codingNInstances}
                            disabled={busy}
                            onChange={(e) => {
                              markCustomProfile();
                              setCodingNInstances(Number(e.target.value) || 3);
                            }}
                            className="rounded border border-border bg-background px-1.5 py-1"
                          />
                        </label>
                      ) : null}
                      <label
                        className="flex items-end gap-2 pb-1"
                        title="编码套件必跑官方 SWE harness resolve（需 Docker + swebench）。部署看板重建 api 前请先 make up-ops-eval（粘性）。"
                      >
                        <input
                          type="checkbox"
                          checked={true}
                          disabled
                          readOnly
                        />
                        <span className="text-[11px] leading-tight">
                          harness resolve（必开）
                          {caps.coding_harness === false ? (
                            <span className="ml-1 text-destructive">
                              不可用
                            </span>
                          ) : null}
                        </span>
                      </label>
                      {selectedSuites.has("coding") &&
                      caps.coding_harness === false ? (
                        <p className="basis-full text-[11px] text-destructive">
                          当前环境无 harness；请先 make up-ops-eval 后重建 api。
                        </p>
                      ) : null}
                    </>
                  ) : null}
                </div>

                {needsLiveModel ? (
                  <div className="mt-3 space-y-2 rounded-md border border-border bg-muted/10 p-3">
                    <p className="text-[11px] font-medium text-muted-foreground">
                      评测模型（本轮）
                    </p>
                    <div className="grid gap-2 sm:grid-cols-2">
                      <label className="grid gap-1 text-xs">
                        <span className="text-[11px] text-muted-foreground">
                          Provider
                        </span>
                        <select
                          value={modelProvider}
                          disabled={busy}
                          onChange={(e) => {
                            markCustomProfile();
                            applyProviderPreset(e.target.value);
                          }}
                          className="rounded border border-border bg-background px-1.5 py-1"
                        >
                          {PROVIDER_PRESETS.map((p: ProviderPreset) => (
                            <option key={p.id} value={p.id}>
                              {p.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="grid gap-1 text-xs">
                        <span className="text-[11px] text-muted-foreground">
                          API style
                        </span>
                        <select
                          value={modelApiStyle}
                          disabled={busy}
                          onChange={(e) => {
                            markCustomProfile();
                            setModelApiStyle(e.target.value as ApiStyle);
                          }}
                          className="rounded border border-border bg-background px-1.5 py-1"
                        >
                          <option value="openai">openai</option>
                          <option value="anthropic">anthropic</option>
                        </select>
                      </label>
                      <label className="grid gap-1 text-xs sm:col-span-2">
                        <span className="text-[11px] text-muted-foreground">
                          Model
                        </span>
                        <input
                          value={modelName}
                          disabled={busy}
                          onChange={(e) => {
                            markCustomProfile();
                            setModelName(e.target.value);
                          }}
                          className="rounded border border-border bg-background px-1.5 py-1"
                        />
                      </label>
                      <label className="grid gap-1 text-xs sm:col-span-2">
                        <span className="text-[11px] text-muted-foreground">
                          Base URL
                        </span>
                        <input
                          value={modelBaseUrl}
                          disabled={busy}
                          onChange={(e) => {
                            markCustomProfile();
                            setModelBaseUrl(e.target.value);
                          }}
                          className="rounded border border-border bg-background px-1.5 py-1"
                        />
                      </label>
                      <div className="grid gap-1 text-xs sm:col-span-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="text-[11px] text-muted-foreground">
                            API key
                            {apiKeySaveFlash ? (
                              <span className="ml-2 text-emerald-700 dark:text-emerald-300">
                                已保存
                              </span>
                            ) : null}
                            {apiKeyStored && !apiKeyEditing ? (
                              <span className="ml-2 text-muted-foreground">
                                （本机已存）
                              </span>
                            ) : null}
                          </span>
                          <div className="flex flex-wrap gap-2">
                            {apiKeyStored && !apiKeyEditing ? (
                              <button
                                type="button"
                                disabled={busy}
                                className="text-[11px] underline disabled:opacity-40"
                                onClick={() => setApiKeyEditing(true)}
                              >
                                更换
                              </button>
                            ) : null}
                            {apiKeyDirty || apiKeyEditing ? (
                              <button
                                type="button"
                                disabled={busy || !modelApiKey.trim()}
                                className="text-[11px] underline disabled:opacity-40"
                                onClick={() => void saveApiKey()}
                              >
                                保存到本机
                              </button>
                            ) : null}
                            {apiKeyStored || modelApiKey ? (
                              <button
                                type="button"
                                disabled={busy}
                                className="text-[11px] text-destructive underline disabled:opacity-40"
                                onClick={() => void clearApiKey()}
                              >
                                清除
                              </button>
                            ) : null}
                          </div>
                        </div>
                        {apiKeyEditing || !apiKeyStored ? (
                          <input
                            type="password"
                            autoComplete="off"
                            value={modelApiKey}
                            disabled={busy}
                            placeholder={
                              storedApiKey ? "粘贴新 key…" : "必填"
                            }
                            onChange={(e) => {
                              markCustomProfile();
                              setModelApiKey(e.target.value);
                            }}
                            className="rounded border border-border bg-background px-1.5 py-1"
                          />
                        ) : (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => setApiKeyEditing(true)}
                            className="rounded border border-dashed border-border bg-muted/20 px-1.5 py-1 text-left text-[11px] text-muted-foreground hover:bg-muted"
                          >
                            ••••••••（点击更换）
                          </button>
                        )}
                      </div>
                      <label className="grid gap-1 text-xs">
                        <span className="text-[11px] text-muted-foreground">
                          Context window
                        </span>
                        <input
                          type="number"
                          min={1024}
                          value={modelContextWindow || ""}
                          disabled={busy}
                          onChange={(e) => {
                            markCustomProfile();
                            setModelContextWindow(
                              e.target.value
                                ? Number(e.target.value)
                                : undefined,
                            );
                          }}
                          className="rounded border border-border bg-background px-1.5 py-1"
                        />
                      </label>
                      <div className="flex items-end gap-2">
                        <button
                          type="button"
                          disabled={busy || probeBusy}
                          onClick={() => void probeModel()}
                          className="rounded-md border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-40"
                        >
                          {probeBusy ? "探测中…" : "探测模型"}
                        </button>
                        {probeMessage ? (
                          <span
                            className={`text-[11px] ${
                              probeOk === false
                                ? "text-destructive"
                                : "text-muted-foreground"
                            }`}
                          >
                            {probeMessage}
                          </span>
                        ) : null}
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
          </section>

          {lastFinishedLiveId ? (
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted/20 px-3 py-2 text-xs">
              <span>
                本轮已结束 · {shortId(lastFinishedLiveId)}
              </span>
              <button
                type="button"
                className="underline"
                onClick={() => {
                  historyDeepLinkDoneRef.current = true;
                  setPagePane("history");
                  navigate(opsOfficialPath(secret, lastFinishedLiveId), {
                    replace: true,
                  });
                  setLastFinishedLiveId(null);
                }}
              >
                查看历史详情
              </button>
            </div>
          ) : null}

          {busy ||
          (liveRun && liveRun.id === selectedId) ||
          (selectedId && liveRun) ? (
            <div className="mb-2 text-xs text-muted-foreground">
              {liveRun
                ? `直播 · ${runSuitesLabel(liveRun)} · ${liveRun.status}`
                : "直播"}
            </div>
          ) : null}

          <LiveProgress model={model} />
        </>
  );
}
