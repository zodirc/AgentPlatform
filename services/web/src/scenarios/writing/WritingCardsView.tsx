import { Badge } from "../../components/ui/badge";
import { Card, CardTitle } from "../../components/ui/card";

type WritingCardMeta = {
  path?: string;
  kind?: string;
  title?: string;
};

type WritingCardsArtifact = {
  type?: string;
  cards?: WritingCardMeta[];
  chars?: number;
  available_count?: number;
  summary?: string;
};

type Props = {
  artifacts: Array<Record<string, unknown>>;
};

const KIND_LABEL: Record<string, string> = {
  character: "人物",
  plot: "情节",
  style: "风格",
  general: "通用",
};

export function WritingCardsView({ artifacts }: Props) {
  const item = [...artifacts]
    .reverse()
    .find((a) => a.type === "writing_cards") as WritingCardsArtifact | undefined;
  if (!item) return null;

  const cards = Array.isArray(item.cards) ? item.cards : [];
  const available =
    typeof item.available_count === "number" ? item.available_count : cards.length;

  return (
    <Card className="border-teal-900/50 bg-teal-950/20">
      <CardTitle className="text-teal-200">本轮写定（素材卡）</CardTitle>
      {cards.length === 0 ? (
        <p className="mt-2 text-xs text-slate-400">
          {available > 0
            ? `未自动选中（库中有 ${available} 张卡）。可在对话中点名人物/风格，或 read_file sources/cards/。`
            : "未找到 sources/cards/ 素材卡。"}
        </p>
      ) : (
        <ul className="mt-2 space-y-2 text-xs">
          {cards.map((card, idx) => (
            <li
              key={`${card.path ?? "card"}-${idx}`}
              className="rounded-lg bg-slate-950 px-3 py-2"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-200">
                  {card.title ?? "未命名"}
                </span>
                <Badge variant="default">
                  {KIND_LABEL[String(card.kind ?? "")] ?? String(card.kind ?? "")}
                </Badge>
              </div>
              {card.path ? (
                <p className="mt-1 truncate text-slate-500">{card.path}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {typeof item.chars === "number" && cards.length > 0 ? (
        <p className="mt-2 text-[11px] text-slate-600">
          已 pin {cards.length} 张 · 约 {item.chars} 字
        </p>
      ) : null}
    </Card>
  );
}
