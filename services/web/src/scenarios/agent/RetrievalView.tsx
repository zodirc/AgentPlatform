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
  index?: {
    index_lag?: boolean;
    synced_on_query?: boolean;
    hint?: string;
  };
};

type Props = {
  artifacts: Array<Record<string, unknown>>;
};

const MODE_LABEL: Record<string, string> = {
  hybrid: "hybrid",
  vector: "向量",
  keyword: "关键词",
  "keyword-fallback": "关键词降级",
  none: "无",
};

function resolveModeLabel(item: RetrievalArtifact): {
  label: string;
  lag: boolean;
} {
  const summary = String(item.summary ?? "");
  const indexLag = Boolean(item.index?.index_lag);
  const mode = String(item.mode ?? "none");
  const fallback =
    mode === "keyword-fallback" ||
    summary.includes("keyword-fallback") ||
    indexLag;
  if (fallback) {
    return { label: MODE_LABEL["keyword-fallback"], lag: true };
  }
  return { label: MODE_LABEL[mode] ?? mode, lag: false };
}

export function RetrievalView({ artifacts }: Props) {
  const items = artifacts.filter(
    (a) => a.type === "retrieval",
  ) as RetrievalArtifact[];
  if (!items.length) return null;

  return (
    <Card className="min-w-0 overflow-hidden border-primary/30 bg-primary/10">
      <CardTitle className="text-primary">资料检索</CardTitle>
      <ul className="mt-2 min-w-0 space-y-3 text-xs">
        {items.map((item, idx) => {
          const hits = Array.isArray(item.hits) ? item.hits : [];
          const hitCount =
            typeof item.hit_count === "number" ? item.hit_count : hits.length;
          const { label, lag } = resolveModeLabel(item);
          return (
            <li
              key={idx}
              className="min-w-0 overflow-hidden rounded-lg bg-background px-3 py-2"
            >
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="min-w-0 max-w-full break-words font-medium text-foreground">
                  {item.query ? `「${item.query}」` : "检索"}
                </span>
                <Badge variant="default">{label}</Badge>
                {lag ? <Badge variant="default">index_lag</Badge> : null}
                <span className="shrink-0 text-muted-foreground">
                  {hitCount} 条命中
                </span>
              </div>
              {lag && item.index?.hint ? (
                <p className="mt-1 break-words text-warning">
                  {item.index.hint}
                </p>
              ) : null}
              {item.summary ? (
                <p className="mt-1 break-words text-muted-foreground">
                  {String(item.summary)}
                </p>
              ) : null}
              {hits.length > 0 ? (
                <ul className="mt-2 min-w-0 space-y-1.5 border-t border-border pt-2">
                  {hits.slice(0, 5).map((hit, i) => (
                    <li key={i} className="min-w-0 overflow-hidden text-muted-foreground">
                      <div className="flex min-w-0 items-baseline gap-1.5">
                        <span
                          className="min-w-0 flex-1 truncate font-mono text-[11px] text-primary"
                          title={hit.path ?? "source"}
                        >
                          {hit.path ?? "source"}
                        </span>
                        {hit.citation_id ? (
                          <span
                            className="shrink-0 text-primary"
                            title={hit.citation_id}
                          >
                            [{hit.citation_id}]
                          </span>
                        ) : null}
                        {typeof hit.score === "number" ? (
                          <span className="shrink-0 text-muted-foreground/80">
                            {hit.score.toFixed(3)}
                          </span>
                        ) : null}
                      </div>
                      {hit.excerpt ? (
                        <p className="mt-0.5 line-clamp-2 break-words text-muted-foreground">
                          {hit.excerpt}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : hitCount === 0 ? (
                <p className="mt-2 break-words text-warning">
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
