export type OpeningPondItem = {
  id: string;
  title: string;
  who?: string;
  where?: string;
  want?: string;
  chapter_job?: string;
  opening?: string;
  arc?: string;
  flavor?: string;
  start_kind?: string;
  promise?: string;
  summary?: string;
};

export type OpeningPondsArtifact = {
  type?: "opening_ponds";
  ponds_id?: string;
  summary?: string;
  awaiting_choice?: boolean;
  items?: OpeningPondItem[];
};

export const START_KIND_LABELS: Record<string, string> = {
  self_notice: "自己发觉能变强",
  pulled_in: "被卷进已在运转的事",
  granted_path: "系统/金手指落到身上",
  world_already: "超凡已是这城的日常",
  no_extraordinary: "先过日子，超凡往后放",
};

export const PROMISE_LABELS: Record<string, string> = {
  power_steps: "变强台阶",
  costly_truth: "查清会伤人的真相",
  survive_relation: "在关系里活下去",
  dread_decode: "解密/恐惧",
  social_place: "社会位置改变",
};

/**
 * Wire token for the「我要其他的」check. Chat hides this bubble;
 * unused start_kind steering is the sidecar block.
 */
export const MORE_PONDS_MESSAGE = "我要其他的";

function clip(raw: unknown, max: number): string {
  const text = String(raw ?? "").trim();
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

export function startKindLabel(token: string | undefined): string {
  if (!token) return "";
  return START_KIND_LABELS[token] || token;
}

export function promiseLabel(token: string | undefined): string {
  if (!token) return "";
  return PROMISE_LABELS[token] || token;
}

export function pondPhysicsLine(item: OpeningPondItem): string {
  if (item.flavor) {
    return item.title ? `${item.title} · ${item.flavor}` : item.flavor;
  }
  return [startKindLabel(item.start_kind), promiseLabel(item.promise)]
    .filter(Boolean)
    .join(" · ");
}

export function pondContrastLine(items: OpeningPondItem[]): string {
  return items
    .map((item) => pondPhysicsLine(item).replace(/ · /g, "·"))
    .filter(Boolean)
    .join(" ｜ ");
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
      opening: clip(rec.opening, 400) || undefined,
      arc: clip(rec.arc, 400) || undefined,
      flavor: clip(rec.flavor, 160) || undefined,
      start_kind: clip(rec.start_kind, 32) || undefined,
      promise: clip(rec.promise, 32) || undefined,
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
    if (ev.type === "opening.ponds" && ev.payload) {
      found = openingPondsFromEventPayload(ev.payload);
    }
  }
  return found;
}

/**
 * Wire token for the next turn after a card check. Chat hides this bubble;
 * opening / arc / flavor live in the workspace sidecar.
 */
export function formatSelectPondMessage(item: OpeningPondItem): string {
  const title = (item.title || item.id || "").trim();
  return `采用此开篇「${title}」`;
}

const COMMIT_POND_RE =
  /(?:按开篇候选|采用此开篇|按此开篇)[「『](.+?)[」』]/;
const COMMIT_POND_PREFIX_RE = /^(?:按开篇候选|采用此开篇|按此开篇)/;

export type OpeningChoice =
  | { kind: "commit"; title: string }
  | { kind: "more" };

/** 勾选/换一组是 UI 动作，不是用户输入。仅作下一回合的令牌。 */
export function openingChoiceFromUserInput(
  text: string | null | undefined,
): OpeningChoice | null {
  const raw = (text || "").replace(/^\uFEFF/, "").trim();
  if (!raw) return null;
  if (raw === MORE_PONDS_MESSAGE || raw.startsWith("这几个都不合适")) {
    return { kind: "more" };
  }
  if (!COMMIT_POND_PREFIX_RE.test(raw)) return null;
  const match = COMMIT_POND_RE.exec(raw);
  const title = match?.[1]?.trim();
  return { kind: "commit", title: title || raw };
}

export function isOpeningChoiceMessage(
  text: string | null | undefined,
): boolean {
  return openingChoiceFromUserInput(text) != null;
}

/** 历史项是否不应画成「你」的输入气泡。 */
export function turnHidesUserInput(turn: {
  user_input?: string | null;
  hideUserInput?: boolean;
}): boolean {
  return Boolean(turn.hideUserInput) || isOpeningChoiceMessage(turn.user_input);
}

export function pondItemSelected(
  item: OpeningPondItem,
  selectedTitle: string | null | undefined,
): boolean {
  if (!selectedTitle) return false;
  return item.title === selectedTitle || item.id === selectedTitle;
}

export function visibleChatUserInputs(
  inputs: Array<string | null | undefined>,
): string[] {
  return inputs
    .map((row) => (row || "").trim())
    .filter((row) => row.length > 0 && !isOpeningChoiceMessage(row));
}
