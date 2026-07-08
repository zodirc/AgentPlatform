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
