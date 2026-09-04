export type OpeningPondItem = {
  id: string;
  title: string;
  who?: string;
  where?: string;
  want?: string;
  chapter_job?: string;
  summary?: string;
};

export type OpeningPondsArtifact = {
  type?: "opening_ponds";
  ponds_id?: string;
  summary?: string;
  awaiting_choice?: boolean;
  items?: OpeningPondItem[];
};

export const MORE_PONDS_MESSAGE =
  "这几个都不合适。再给 2～3 个互不换皮的开篇候选（跟着谁、站在哪、眼下要什么、超凡怎么开始都要换）。至少一份是主角在有人的日子里自己发觉能做什么，不要三份都是开窗死人、灵异出事、城市异变。";

function clip(raw: unknown, max: number): string {
  const text = String(raw ?? "").trim();
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

export function normalizeOpeningPondItems(
  raw: unknown,
): OpeningPondItem[] {
  if (!Array.isArray(raw)) return [];
  const out: OpeningPondItem[] = [];
  for (let i = 0; i < raw.length && out.length < 4; i += 1) {
    const row = raw[i];
    if (!row || typeof row !== "object") continue;
    const rec = row as Record<string, unknown>;
    const title = clip(rec.title, 80);
    if (!title) continue;
    out.push({
      id: clip(rec.id, 32) || `pond-${i + 1}`,
      title,
      who: clip(rec.who, 240) || undefined,
      where: clip(rec.where, 240) || undefined,
      want: clip(rec.want, 240) || undefined,
      chapter_job: clip(rec.chapter_job, 240) || undefined,
      summary: clip(rec.summary, 160) || undefined,
    });
  }
  return out;
}

export function normalizeOpeningPondsArtifact(
  raw: Record<string, unknown> | OpeningPondsArtifact | null | undefined,
): OpeningPondsArtifact | null {
  if (!raw || typeof raw !== "object") return null;
  const items = normalizeOpeningPondItems(
    (raw as OpeningPondsArtifact).items,
  );
  if (items.length < 2) return null;
  return {
    type: "opening_ponds",
    ponds_id: raw.ponds_id ? String(raw.ponds_id) : undefined,
    summary: raw.summary ? String(raw.summary) : undefined,
    awaiting_choice:
      typeof raw.awaiting_choice === "boolean" ? raw.awaiting_choice : undefined,
    items,
  };
}

export function openingPondsFromEventPayload(
  payload: Record<string, unknown>,
): OpeningPondsArtifact | null {
  return normalizeOpeningPondsArtifact(payload);
}

export function latestOpeningPondsFromArtifacts(
  artifacts: Array<Record<string, unknown>> | undefined,
): OpeningPondsArtifact | null {
  if (!artifacts?.length) return null;
  let found: OpeningPondsArtifact | null = null;
  for (const art of artifacts) {
    if (art?.type === "opening_ponds") {
      found = normalizeOpeningPondsArtifact(art);
    }
  }
  return found;
}

export function latestOpeningPondsFromEvents(
  events:
    | Array<{ type?: string; payload?: Record<string, unknown> }>
    | undefined,
): OpeningPondsArtifact | null {
  if (!events?.length) return null;
  let found: OpeningPondsArtifact | null = null;
  for (const ev of events) {
    if (ev?.type === "opening.ponds" && ev.payload) {
      found = openingPondsFromEventPayload(ev.payload);
    }
  }
  return found;
}

export function formatSelectPondMessage(item: OpeningPondItem): string {
  const lines = [`按开篇候选「${item.title}」写第一章。`, ""];
  if (item.who) lines.push(`跟着谁：${item.who}`);
  if (item.where) lines.push(`站在哪：${item.where}`);
  if (item.want) lines.push(`眼下要什么：${item.want}`);
  if (item.chapter_job) lines.push(`这一章干什么：${item.chapter_job}`);
  return lines.join("\n").trim();
}
