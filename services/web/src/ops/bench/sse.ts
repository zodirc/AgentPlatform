export async function openAuthorizedHtml(
  href: string,
  secret: string,
): Promise<void> {
  const resp = await fetch(href, {
    headers: { Authorization: `Bearer ${secret}`, Accept: "text/html" },
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(text || `HTTP ${resp.status}`);
  }
  const htmlText = await resp.text();
  const blob = new Blob([htmlText], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const win = window.open(url, "_blank", "noopener,noreferrer");
  if (!win) {
    // Popup blocked — fall back to same-tab navigation via blob.
    window.location.href = url;
  }
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export async function downloadAuthorizedFile(
  href: string,
  secret: string,
  filename: string,
): Promise<void> {
  const resp = await fetch(href, {
    headers: { Authorization: `Bearer ${secret}` },
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(text || `HTTP ${resp.status}`);
  }
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function fetchAuthorizedText(
  href: string,
  secret: string,
): Promise<string> {
  const resp = await fetch(href, {
    headers: { Authorization: `Bearer ${secret}` },
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(text || `HTTP ${resp.status}`);
  }
  return resp.text();
}
export class EventSourcePolyfill {
  private controller = new AbortController();
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string, secret: string) {
    void this.start(url, secret);
  }

  private async start(url: string, secret: string) {
    try {
      const resp = await fetch(url, {
        headers: {
          Authorization: `Bearer ${secret}`,
          Accept: "text/event-stream",
        },
        signal: this.controller.signal,
      });
      if (!resp.ok || !resp.body) {
        this.onerror?.();
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data:"));
          if (line) this.onmessage?.({ data: line.slice(5).trim() });
        }
      }
    } catch {
      if (!this.controller.signal.aborted) this.onerror?.();
    }
  }

  close() {
    this.controller.abort();
  }
}
