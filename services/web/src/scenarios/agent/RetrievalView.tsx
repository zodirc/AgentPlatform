import { Card, CardTitle } from "../../components/ui/card";

type RetrievalArtifact = {
  type?: string;
  query?: string;
  hits?: Array<Record<string, unknown>>;
  summary?: string;
};

type Props = {
  artifacts: Array<Record<string, unknown>>;
};

export function RetrievalView({ artifacts }: Props) {
  const items = artifacts.filter(
    (a) => a.type === "retrieval",
  ) as RetrievalArtifact[];
  if (!items.length) return null;

  return (
    <Card className="border-indigo-900/50 bg-indigo-950/20">
      <CardTitle className="text-indigo-200">检索结果</CardTitle>
      <ul className="mt-2 space-y-2 text-xs">
        {items.map((item, idx) => (
          <li key={idx} className="rounded bg-slate-950 px-3 py-2">
            <div className="text-slate-300">
              {String(item.summary ?? item.query ?? "retrieval")}
            </div>
            {Array.isArray(item.hits) && item.hits.length > 0 ? (
              <ul className="mt-1 text-slate-500">
                {item.hits.slice(0, 5).map((hit, i) => (
                  <li key={i}>
                    {String((hit as { path?: string }).path ?? "hit")} —{" "}
                    {String((hit as { excerpt?: string }).excerpt ?? "").slice(
                      0,
                      80,
                    )}
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
    </Card>
  );
}
