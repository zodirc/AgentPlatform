import { Link } from "react-router-dom";
import { opsEnvelopePath, opsRawPath, opsRetrievalPath } from "./opsPaths";

/** Cross-links between Ops observation pages for one Turn (read-only). */
export function OpsTurnLinks({
  secret,
  turnId,
  current,
}: {
  secret: string;
  turnId: string;
  current: "retrieval" | "envelopes" | "raw";
}) {
  const id = turnId.trim();
  if (!secret || !id) return null;

  const items: { key: typeof current; label: string; to: string }[] = [
    { key: "retrieval", label: "检索审计", to: opsRetrievalPath(secret, id) },
    { key: "envelopes", label: "模型信封", to: opsEnvelopePath(secret, id) },
    { key: "raw", label: "Raw 快照", to: opsRawPath(secret, id) },
  ];

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="text-muted-foreground">同 Turn 观测：</span>
      {items.map((item) =>
        item.key === current ? (
          <span
            key={item.key}
            className="rounded-md border border-primary/40 bg-primary/10 px-2 py-1 text-foreground"
          >
            {item.label}
          </span>
        ) : (
          <Link
            key={item.key}
            to={item.to}
            className="rounded-md border border-border px-2 py-1 text-foreground hover:bg-muted"
          >
            {item.label}
          </Link>
        ),
      )}
    </div>
  );
}
