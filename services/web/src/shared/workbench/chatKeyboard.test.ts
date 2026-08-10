import { describe, expect, it, vi } from "vitest";
import {
  canNavigateInputHistory,
  historyFromUserInputs,
  navigateInputHistory,
  onChatEnterSend,
  onChatInputHistory,
  pushInputHistory,
} from "./chatKeyboard";

function keyEvent(
  key: string,
  opts?: {
    shiftKey?: boolean;
    isComposing?: boolean;
    value?: string;
    selectionStart?: number;
    selectionEnd?: number;
  },
) {
  const value = opts?.value ?? "";
  const selectionStart = opts?.selectionStart ?? 0;
  const selectionEnd = opts?.selectionEnd ?? selectionStart;
  return {
    key,
    shiftKey: opts?.shiftKey ?? false,
    altKey: false,
    ctrlKey: false,
    metaKey: false,
    nativeEvent: { isComposing: opts?.isComposing ?? false },
    preventDefault: vi.fn(),
    currentTarget: {
      value,
      selectionStart,
      selectionEnd,
    },
  } as unknown as React.KeyboardEvent<HTMLTextAreaElement>;
}

describe("onChatEnterSend", () => {
  it("sends on Enter when allowed", () => {
    const send = vi.fn();
    const e = keyEvent("Enter");
    onChatEnterSend(e, send, true);
    expect(e.preventDefault).toHaveBeenCalled();
    expect(send).toHaveBeenCalledOnce();
  });

  it("does not send on Shift+Enter", () => {
    const send = vi.fn();
    const e = keyEvent("Enter", { shiftKey: true });
    onChatEnterSend(e, send, true);
    expect(send).not.toHaveBeenCalled();
  });

  it("does not send while IME composing", () => {
    const send = vi.fn();
    const e = keyEvent("Enter", { isComposing: true });
    onChatEnterSend(e, send, true);
    expect(send).not.toHaveBeenCalled();
  });

  it("does not send when canSend is false", () => {
    const send = vi.fn();
    const e = keyEvent("Enter");
    onChatEnterSend(e, send, false);
    expect(e.preventDefault).toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();
  });
});

describe("pushInputHistory", () => {
  it("skips empty and consecutive duplicates", () => {
    expect(pushInputHistory([], "  ")).toEqual([]);
    expect(pushInputHistory(["a"], "a")).toEqual(["a"]);
    expect(pushInputHistory(["a"], "b")).toEqual(["a", "b"]);
  });

  it("caps length", () => {
    const entries = pushInputHistory(["1", "2", "3"], "4", 3);
    expect(entries).toEqual(["2", "3", "4"]);
  });
});

describe("historyFromUserInputs", () => {
  it("builds oldest to newest without empty dupes", () => {
    expect(
      historyFromUserInputs(["hello", "", "hello", "world", null]),
    ).toEqual(["hello", "world"]);
  });
});

describe("navigateInputHistory", () => {
  const entries = ["one", "two", "three"];

  it("ArrowUp from draft goes to newest", () => {
    expect(
      navigateInputHistory("ArrowUp", {
        entries,
        index: 3,
        draft: "draft",
        current: "draft",
      }),
    ).toEqual({ index: 2, draft: "draft", value: "three" });
  });

  it("ArrowUp walks older and restores draft on ArrowDown", () => {
    const up = navigateInputHistory("ArrowUp", {
      entries,
      index: 2,
      draft: "draft",
      current: "three",
    });
    expect(up).toEqual({ index: 1, draft: "draft", value: "two" });
    expect(
      navigateInputHistory("ArrowDown", {
        entries,
        index: 2,
        draft: "draft",
        current: "three",
      }),
    ).toEqual({ index: 3, draft: "draft", value: "draft" });
  });

  it("ArrowUp at oldest stays on oldest", () => {
    expect(
      navigateInputHistory("ArrowUp", {
        entries,
        index: 0,
        draft: "d",
        current: "one",
      }),
    ).toEqual({ index: 0, draft: "d", value: "one" });
  });
});

describe("canNavigateInputHistory", () => {
  it("allows ArrowUp on first line only", () => {
    const ok = keyEvent("ArrowUp", {
      value: "hello",
      selectionStart: 5,
    });
    expect(canNavigateInputHistory(ok, "ArrowUp")).toBe(true);

    const blocked = keyEvent("ArrowUp", {
      value: "a\nb",
      selectionStart: 3,
    });
    expect(canNavigateInputHistory(blocked, "ArrowUp")).toBe(false);
  });

  it("allows ArrowDown on last line only", () => {
    const ok = keyEvent("ArrowDown", {
      value: "a\nb",
      selectionStart: 3,
    });
    expect(canNavigateInputHistory(ok, "ArrowDown")).toBe(true);

    const blocked = keyEvent("ArrowDown", {
      value: "a\nb",
      selectionStart: 1,
    });
    expect(canNavigateInputHistory(blocked, "ArrowDown")).toBe(false);
  });
});

describe("onChatInputHistory", () => {
  it("applies navigation and prevents default when empty", () => {
    const apply = vi.fn();
    const e = keyEvent("ArrowUp", { value: "", selectionStart: 0 });
    const consumed = onChatInputHistory(
      e,
      { entries: ["prev"], index: 1, draft: "", current: "" },
      apply,
    );
    expect(consumed).toBe(true);
    expect(e.preventDefault).toHaveBeenCalled();
    expect(apply).toHaveBeenCalledWith({
      index: 0,
      draft: "",
      value: "prev",
    });
  });

  it("does not recall history on ArrowUp when draft has content", () => {
    const apply = vi.fn();
    const e = keyEvent("ArrowUp", {
      value: "typing",
      selectionStart: 6,
    });
    const consumed = onChatInputHistory(
      e,
      { entries: ["prev"], index: 1, draft: "typing", current: "typing" },
      apply,
    );
    expect(consumed).toBe(false);
    expect(e.preventDefault).not.toHaveBeenCalled();
    expect(apply).not.toHaveBeenCalled();
  });

  it("still walks history after entering from empty draft", () => {
    const apply = vi.fn();
    const e = keyEvent("ArrowUp", {
      value: "prev",
      selectionStart: 4,
    });
    const consumed = onChatInputHistory(
      e,
      { entries: ["older", "prev"], index: 1, draft: "", current: "prev" },
      apply,
    );
    expect(consumed).toBe(true);
    expect(apply).toHaveBeenCalledWith({
      index: 0,
      draft: "",
      value: "older",
    });
  });
});
