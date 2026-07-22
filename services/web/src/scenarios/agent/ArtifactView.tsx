import { Card, CardTitle } from "../../components/ui/card";

type Props = {
  artifacts: Array<Record<string, unknown>>;
};

export function ArtifactView({ artifacts }: Props) {
  const items = artifacts.filter(
    (a) => a.type === "subagent" || a.type === "retrieval",
  );
  if (!items.length) return null;

  return (
    <Card>
      <CardTitle>Artifacts</CardTitle>
      <ul className="mt-2 space-y-2 text-xs">
        {items.map((item, idx) => (
          <li key={idx} className="rounded bg-background px-3 py-2">
            <span className="text-muted-foreground">{String(item.type)}</span>
            {" — "}
            {String(
              item.summary ??
                item.event ??
                item.title ??
                JSON.stringify(item).slice(0, 120),
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
