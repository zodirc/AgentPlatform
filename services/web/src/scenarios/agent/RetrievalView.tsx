import { Badge } from "../../components/ui/badge";
import { Card, CardTitle } from "../../components/ui/card";

type RetrievalHit = {
  path?: string;
  excerpt?: string;
  citation_id?: string;
  score?: number;
};

type RetrievalArtifact = {
  type?: string;
  query?: string;
  mode?: string;
  hit_count?: number;
  hits?: RetrievalHit[];
  summary?: string;
};

type Props = {
  artifacts: Array<Record<string, unknown>>;
};

const MODE_LABEL: Record<string, string> = {
  vector: "向量",
  keyword: "关键词",
  none: "无",
};

export function RetrievalView({ artifacts }: Props) {
  const items = artifacts.filter(
    (a) => a.type === "retrieval",
  ) as RetrievalArtifact[];
  if (!items.length) return null;

  return (
    <Card className="border-indigo-900/50 bg-indigo-950/20">
      <CardTitle className="text-indigo-200">资料检索</CardTitle>
      <ul className="mt-2 space-y-3 text-xs">
        {items.map((item, idx) => {
          const hits = Array.isArray(item.hits) ? item.hits : [];
          const hitCount =
            typeof item.hit_count === "number" ? item.hit_count : hits.length;
          const mode = String(item.mode ?? "none");
          return (
            <li key={idx} className="rounded-lg bg-slate-950 px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-200">
                  {item.query ? `「${item.query}」` : "检索"}
                </span>
                <Badge variant="default">{MODE_LABEL[mode] ?? mode}</Badge>
                <span className="text-slate-500">{hitCount} 条命中</span>
              </div>
              {item.summary ? (
                <p className="mt-1 text-slate-400">{String(item.summary)}</p>
              ) : null}
              {hits.length > 0 ? (
                <ul className="mt-2 space-y-1.5 border-t border-slate-800 pt-2">
                  {hits.slice(0, 5).map((hit, i) => (
                    <li key={i} className="text-slate-400">
                      <span className="text-sky-300">
                        {hit.path ?? "source"}
                      </span>
                      {hit.citation_id ? (
                        <span className="ml-1 text-violet-300">
                          [{hit.citation_id}]
                        </span>
                      ) : null}
                      {typeof hit.score === "number" ? (
                        <span className="ml-1 text-slate-600">
                          {hit.score.toFixed(3)}
                        </span>
                      ) : null}
                      {hit.excerpt ? (
                        <p className="mt-0.5 line-clamp-2 text-slate-500">
                          {hit.excerpt}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : hitCount === 0 ? (
                <p className="mt-2 text-amber-400/90">
                  未找到匹配资料 — 模型无法引用 sources/ 中的证据
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
