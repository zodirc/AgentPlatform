import { useCallback, useEffect, useRef } from "react";
import type { KeyboardEvent } from "react";
import {
  historyFromUserInputs,
  onChatInputHistory,
  pushInputHistory,
  type InputHistoryNavResult,
} from "./chatKeyboard";

type Options = {
  /** Reset / reseeds when this changes (e.g. session id). */
  sessionKey?: string | null;
  /** Prior user messages for the current session (oldest → newest). */
  seedInputs?: Array<string | null | undefined>;
};

/**
 * Shell-style ↑/↓ prompt history for the chat composer.
 * Remembers sends; seeds from turn history when the session loads.
 */
export function useChatInputHistory(options: Options = {}) {
  const { sessionKey = null, seedInputs = [] } = options;
  const entriesRef = useRef<string[]>([]);
  const indexRef = useRef(0);
  const draftRef = useRef("");
  const seededKeyRef = useRef<string | null>(null);
  const seedSignature = JSON.stringify(historyFromUserInputs(seedInputs));

  useEffect(() => {
    const key = sessionKey ?? "";
    const seeded = JSON.parse(seedSignature) as string[];

    if (seededKeyRef.current !== key) {
      seededKeyRef.current = key;
      entriesRef.current = seeded;
      indexRef.current = seeded.length;
      draftRef.current = "";
      return;
    }
    if (entriesRef.current.length === 0 && seeded.length > 0) {
      entriesRef.current = seeded;
      indexRef.current = seeded.length;
    }
  }, [sessionKey, seedSignature]);

  const remember = useCallback((text: string) => {
    entriesRef.current = pushInputHistory(entriesRef.current, text);
    indexRef.current = entriesRef.current.length;
    draftRef.current = "";
  }, []);

  const onKeyDown = useCallback(
    (
      e: KeyboardEvent<HTMLTextAreaElement>,
      current: string,
      setMessage: (value: string) => void,
    ) => {
      onChatInputHistory(
        e,
        {
          entries: entriesRef.current,
          index: indexRef.current,
          draft: draftRef.current,
          current,
        },
        (next: InputHistoryNavResult) => {
          indexRef.current = next.index;
          draftRef.current = next.draft;
          setMessage(next.value);
          requestAnimationFrame(() => {
            const el = e.currentTarget;
            if (!el) return;
            const pos = next.value.length;
            el.selectionStart = pos;
            el.selectionEnd = pos;
          });
        },
      );
    },
    [],
  );

  /** Keep draft in sync while typing (and exit browse mode on edit). */
  const onEdit = useCallback((value: string) => {
    if (indexRef.current < entriesRef.current.length) {
      indexRef.current = entriesRef.current.length;
    }
    draftRef.current = value;
  }, []);

  return { remember, onKeyDown, onEdit };
}
