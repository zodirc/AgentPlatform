import type { MetricAgg } from "./types";
import { describeMetric } from "./metricGlossary";
import { MetricGuide } from "./MetricGuide";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type SummaryPaneModel = Record<string, any>;

export function SummaryPane({ model }: { model: SummaryPaneModel }) {
  const { scoredRunCount, suiteFilter, setSuiteFilter, metricAggs } = model;
  return (
        <section className="mb-5 rounded-xl border border-border p-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">指标汇总</h2>
              <p className="text-[11px] text-muted-foreground">
                仅统计 <strong>completed</strong>；已排除 running / cancelled /
                dry / skip_api / reclaimed / 仅 hash 冒烟
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                n · 最低 · 中位 · 平均 · 最高 · 最近一次。
                {scoredRunCount > 0
                  ? ` 当前 ${scoredRunCount} 次 completed 计入。`
                  : ""}
                冒烟跑次即使 completed 也不作效果结论。
              </p>
            </div>
            <label className="flex items-center gap-1.5 text-xs">
              筛选
              <select
                className="rounded-md border border-border bg-background px-2 py-1"
                value={suiteFilter}
                onChange={(e) => setSuiteFilter(e.target.value)}
              >
                <option value="">全部套件</option>
                <option value="retrieval">含 retrieval</option>
                <option value="context">含 context</option>
                <option value="coding">含 coding</option>
              </select>
            </label>
          </div>

          <div className="mt-3">
            <MetricGuide />
          </div>

          {metricAggs.length === 0 ? (
            <p className="mt-4 text-xs text-muted-foreground">
              还没有可汇总的 completed
              跑次。跑完整场并成功结束后，指标会出现在这里。
            </p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-xs">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="border-b border-border py-2 pr-2 font-medium">
                      指标
                    </th>
                    <th className="border-b border-border py-2 pr-2 font-medium">
                      n
                    </th>
                    <th className="border-b border-border py-2 pr-2 font-medium">
                      最低
                    </th>
                    <th className="border-b border-border py-2 pr-2 font-medium">
                      中位
                    </th>
                    <th className="border-b border-border py-2 pr-2 font-medium">
                      平均
                    </th>
                    <th className="border-b border-border py-2 pr-2 font-medium">
                      最高
                    </th>
                    <th className="border-b border-border py-2 font-medium">
                      最近
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {metricAggs.map((row: MetricAgg) => {
                    const info = describeMetric(row.key);
                    return (
                    <tr key={row.key} className="border-b border-border/60">
                      <td className="py-1.5 pr-2" title={`${info.en} — ${info.effect}`}>
                        <div className="font-medium">
                          {info.scope ? `${info.scope} · ${info.zh}` : info.zh}
                        </div>
                        <div className="font-mono text-[11px] text-muted-foreground">
                          {row.key}
                          <span className="ml-1.5 font-sans">
                            {info.en}
                          </span>
                        </div>
                        <div className="mt-0.5 text-[11px] text-muted-foreground">
                          {info.effect}
                        </div>
                      </td>
                      <td className="py-1.5 pr-2 tabular-nums text-muted-foreground">
                        {row.n}
                      </td>
                      <td className="py-1.5 pr-2 tabular-nums">
                        {row.min.toFixed(4)}
                      </td>
                      <td className="py-1.5 pr-2 tabular-nums">
                        {row.median.toFixed(4)}
                      </td>
                      <td className="py-1.5 pr-2 tabular-nums font-medium">
                        {row.mean.toFixed(4)}
                      </td>
                      <td className="py-1.5 pr-2 tabular-nums">
                        {row.max.toFixed(4)}
                      </td>
                      <td className="py-1.5 tabular-nums text-muted-foreground">
                        {row.latest.toFixed(4)}
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
  );
}
