import type { KeyboardEvent } from "react";

/** Enter 发送；Shift+Enter 换行；IME 组合输入中不发送 */
export function onChatEnterSend(
  e: KeyboardEvent<HTMLTextAreaElement>,
  send: () => void,
  canSend: boolean,
) {
  if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
  e.preventDefault();
  if (canSend) send();
}

const DEFAULT_HISTORY_MAX = 50;

/** Append a sent prompt; skip empty / consecutive duplicates. */
export function pushInputHistory(
  entries: string[],
  text: string,
  max = DEFAULT_HISTORY_MAX,
): string[] {
  const t = text.trim();
  if (!t) return entries;
  if (entries[entries.length - 1] === t) return entries;
  const next = [...entries, t];
  return next.length > max ? next.slice(next.length - max) : next;
}

/** Build history from prior turn user inputs (oldest → newest). */
export function historyFromUserInputs(
  inputs: Array<string | null | undefined>,
  max = DEFAULT_HISTORY_MAX,
): string[] {
  let entries: string[] = [];
  for (const raw of inputs) {
    entries = pushInputHistory(entries, raw ?? "", max);
  }
  return entries;
}

/**
 * Whether ↑/↓ should recall history instead of moving the caret.
 * Only when: no modifiers, not composing, collapsed caret, and caret is on
 * the first line (↑) or last line (↓) — so multiline editing still works.
 */
export function canNavigateInputHistory(
  e: KeyboardEvent<HTMLTextAreaElement>,
  key: "ArrowUp" | "ArrowDown",
): boolean {
  if (e.key !== key) return false;
  if (e.nativeEvent.isComposing) return false;
  if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return false;
  const el = e.currentTarget;
  const value = el.value;
  const start = el.selectionStart ?? 0;
  const end = el.selectionEnd ?? 0;
  if (start !== end) return false;
  if (key === "ArrowUp") {
    return !value.slice(0, start).includes("\n");
  }
  return !value.slice(end).includes("\n");
}

export type InputHistoryNavState = {
  entries: string[];
  /** `entries.length` means editing the live draft. */
  index: number;
  draft: string;
  current: string;
};

export type InputHistoryNavResult = {
  index: number;
  draft: string;
  value: string;
};

/** Shell-style history step. Returns null when nothing changes. */
export function navigateInputHistory(
  key: "ArrowUp" | "ArrowDown",
  state: InputHistoryNavState,
): InputHistoryNavResult | null {
  const { entries, index, draft, current } = state;
  if (entries.length === 0) return null;

  if (key === "ArrowUp") {
    if (index <= 0) {
      if (index === 0) return { index: 0, draft, value: entries[0] ?? "" };
      return null;
    }
    const atDraft = index >= entries.length;
    const nextIndex = atDraft ? entries.length - 1 : index - 1;
    return {
      index: nextIndex,
      draft: atDraft ? current : draft,
      value: entries[nextIndex] ?? "",
    };
  }

  // ArrowDown
  if (index >= entries.length) return null;
  const nextIndex = index + 1;
  if (nextIndex >= entries.length) {
    return { index: entries.length, draft, value: draft };
  }
  return {
    index: nextIndex,
    draft,
    value: entries[nextIndex] ?? "",
  };
}

/**
 * Handle ↑/↓ history recall on a chat textarea.
 * Returns true if the event was consumed.
 */
export function onChatInputHistory(
  e: KeyboardEvent<HTMLTextAreaElement>,
  state: InputHistoryNavState,
  apply: (next: InputHistoryNavResult) => void,
): boolean {
  const key =
    e.key === "ArrowUp" ? "ArrowUp" : e.key === "ArrowDown" ? "ArrowDown" : null;
  if (!key) return false;
  if (!canNavigateInputHistory(e, key)) return false;
  const next = navigateInputHistory(key, state);
  if (!next) return false;
  e.preventDefault();
  apply(next);
  return true;
}
