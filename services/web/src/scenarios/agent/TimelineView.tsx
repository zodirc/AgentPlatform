import { Card, CardTitle } from "../../components/ui/card";

type TimelineItem = {
  tool_call_id?: string;
  tool_name?: string;
  status?: string;
  stream_output?: string;
  summary?: string;
};

type Props = {
  items: TimelineItem[];
};

export function TimelineView({ items }: Props) {
  return (
    <Card>
      <CardTitle>工具时间线</CardTitle>
      <ul className="mt-2 space-y-2 text-xs">
        {items.map((t) => (
          <li key={String(t.tool_call_id)} className="rounded bg-slate-950 px-3 py-2">
            <div>
              {String(t.tool_name)} — {String(t.status)}
            </div>
            {t.stream_output ? (
              <pre className="mt-1 whitespace-pre-wrap text-slate-400">{String(t.stream_output)}</pre>
            ) : null}
            {t.summary ? <p className="mt-1 text-slate-500">{String(t.summary)}</p> : null}
          </li>
        ))}
        {!items.length && <li className="text-slate-500">暂无工具调用</li>}
      </ul>
    </Card>
  );
}
