import { describe, expect, it, vi } from "vitest";
import { onChatEnterSend } from "./chatKeyboard";

function keyEvent(
  key: string,
  opts?: { shiftKey?: boolean; isComposing?: boolean },
) {
  return {
    key,
    shiftKey: opts?.shiftKey ?? false,
    nativeEvent: { isComposing: opts?.isComposing ?? false },
    preventDefault: vi.fn(),
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
