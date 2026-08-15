import {
  OVERVIEW_HEADLINE_LEAVES,
  describeMetric,
  metricLeaf,
  metricScope,
  type MetricScopeId,
} from "./metricGlossary";

const GROUP_ORDER: MetricScopeId[] = [
  "code",
  "beir",
  "cmteb",
  "context",
  "other",
];

function isSuiteMacroKey(key: string): boolean {
  if (
    /^(official\.)?(coding_infer|coding|retrieval_zh|retrieval|context)\./.test(
      key,
    )
  ) {
    return true;
  }
  return (OVERVIEW_HEADLINE_LEAVES as readonly string[]).includes(key);
}

export function MetricGuide() {
  return (
    <div className="rounded-lg border border-border/70 px-3 py-2 text-xs">
      <div className="font-semibold text-foreground">怎么读这些数</div>
      <p className="mt-1 text-muted-foreground">
        冒烟（编码 n5 · 检索每套 20 题 · 上下文截题）
        <strong className="text-foreground">只看方向，不作效果结论</strong>
        。立锚要：编码 n25+harness、检索每套 n≥100、上下文不截题。
      </p>
      <ul className="mt-2 space-y-1 text-muted-foreground">
        <li>
          <span className="text-foreground">编码</span>
          ：效果看官方解决率（失败测试是否变绿）。补丁交出率只说明交了 diff。
        </li>
        <li>
          <span className="text-foreground">检索是两套题</span>
          ：英文 BEIR 与中文 C-MTEB 分栏，同名指标不要混加。
        </li>
        <li>
          <span className="text-foreground">R@100</span>
          ：金标文档进没进前 100。只问中没中，排第 3 和第 80 一样算中。英文第一验收位看它。
        </li>
        <li>
          <span className="text-foreground">nDCG@10</span>
          ：前 10 名排得准不准（归一化折损累计增益：越往后名次越不值钱，再除以「理想排名」压到
          0–1）。只问排位，不问「意思像不像」。1 个金标时：第 1 名=1、第 2 名≈0.63、第
          10 名≈0.29、前 10 没有=0。金标在第 50 名则这项仍是 0，所以召回不进前 10，这项抬不起来。
        </li>
        <li>
          <span className="text-foreground">上下文</span>
          ：F1 比的是<strong className="text-foreground">用词</strong>
          ，不是意思像不像。两边先去掉标点/a/an/the，再按词对齐；多写、漏写都扣分。例如标准答案
          berlin、模型写 answer berlin，多了一个 answer，F1 约 0.67。EM
          要求规范化后整句完全一样才得 1。
        </li>
      </ul>
    </div>
  );
}

/** Current-run headlines, grouped so BEIR / C-MTEB are not one mixed list. */
export function HeadlineMetrics({
  metrics,
}: {
  metrics: Record<string, number>;
}) {
  const byScope = new Map<
    MetricScopeId,
    { key: string; value: number; leaf: string }[]
  >();
  const seen = new Set<string>();
  for (const want of OVERVIEW_HEADLINE_LEAVES) {
    for (const [key, value] of Object.entries(metrics)) {
      if (!Number.isFinite(value)) continue;
      if (!isSuiteMacroKey(key)) continue;
      if (metricLeaf(key) !== want) continue;
      if (key.includes("_incl_infra")) continue;
      const { id } = metricScope(key);
      const sig = `${id}:${want}`;
      if (seen.has(sig)) continue;
      seen.add(sig);
      const rows = byScope.get(id) || [];
      rows.push({ key, value, leaf: want });
      byScope.set(id, rows);
    }
  }
  const groups = GROUP_ORDER.filter((id) => (byScope.get(id) || []).length);
  if (!groups.length) return null;
  return (
    <div className="space-y-2.5">
      {groups.map((id) => {
        const rows = byScope.get(id) || [];
        const scope = metricScope(rows[0].key).zh;
        return (
          <div key={id}>
            <div className="mb-1 text-[11px] font-medium text-muted-foreground">
              {scope || "其它"}
            </div>
            <ul className="space-y-1 text-xs">
              {rows.map(({ key, value }) => {
                const info = describeMetric(key);
                return (
                  <li
                    key={key}
                    className="flex items-baseline justify-between gap-3"
                    title={`${info.en} — ${info.effect}`}
                  >
                    <span className="min-w-0">
                      <span className="font-medium">{info.zh}</span>
                      <span className="ml-1 font-mono text-[11px] text-muted-foreground">
                        {info.leaf}
                      </span>
                    </span>
                    <span className="shrink-0 tabular-nums">
                      {value.toFixed(4)}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
