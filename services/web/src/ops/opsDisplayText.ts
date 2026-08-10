/**
 * Coerce API / run payload values into a safe React text child.
 * Prevents React #31 when ErrorBody `{code, message, details}` (or other
 * objects) are rendered as children.
 */
export function opsDisplayText(value: unknown, fallback = ""): string {
  if (value == null || value === false) return fallback;
  if (typeof value === "string") return value || fallback;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (typeof value === "object") {
    const rec = value as Record<string, unknown>;
    if (typeof rec.message === "string" && rec.message.trim()) {
      const code = typeof rec.code === "string" ? rec.code.trim() : "";
      return code ? `${code}: ${rec.message}` : rec.message;
    }
    if (typeof rec.detail === "string" && rec.detail.trim()) {
      return rec.detail;
    }
    if (typeof rec.error === "string" && rec.error.trim()) {
      return rec.error;
    }
    if (rec.error != null && typeof rec.error === "object") {
      return opsDisplayText(rec.error, fallback);
    }
    try {
      return JSON.stringify(value);
    } catch {
      return fallback || "[unprintable]";
    }
  }
  return fallback;
}

/** Prefer ErrorBody.message / FastAPI detail / raw text from an HTTP JSON body. */
export function opsApiErrorText(
  body: unknown,
  fallback: string,
): string {
  if (body == null) return fallback;
  if (typeof body === "string") {
    const trimmed = body.trim();
    if (!trimmed) return fallback;
    try {
      return opsApiErrorText(JSON.parse(trimmed), trimmed);
    } catch {
      return trimmed;
    }
  }
  if (typeof body !== "object") return String(body) || fallback;
  const rec = body as Record<string, unknown>;
  const fromError = opsDisplayText(rec.error, "");
  if (fromError) return fromError;
  const fromDetail = opsDisplayText(rec.detail, "");
  if (fromDetail) return fromDetail;
  const fromMessage = opsDisplayText(rec.message, "");
  if (fromMessage) return fromMessage;
  return fallback;
}
