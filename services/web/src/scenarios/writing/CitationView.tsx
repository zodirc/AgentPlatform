import { Badge } from "../../components/ui/badge";
import { Card, CardTitle } from "../../components/ui/card";

type CitationHit = {
  tool_name?: string;
  summary?: string;
  status?: string;
};

type Props = {
  items: CitationHit[];
};

export function CitationView({ items }: Props) {
  const citations = items.filter((t) => t.tool_name === "check_citation");
  if (!citations.length) return null;

  return (
    <Card className="border-sky-900/50 bg-sky-950/20">
      <CardTitle className="text-sky-200">引用核对</CardTitle>
      <ul className="mt-2 space-y-2 text-xs">
        {citations.map((item, idx) => {
          const valid = String(item.summary ?? "").includes("valid");
          return (
            <li key={idx} className="rounded bg-slate-950 px-3 py-2">
              <Badge variant={valid ? "success" : "warning"}>
                {valid ? "valid" : "invalid"}
              </Badge>
              <span className="ml-2 text-slate-300">
                {String(item.summary ?? "")}
              </span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
