/** Heuristic: highlight error-looking Ops run log lines (no backend level field). */
export function isOpsErrorLogLine(text: string | null | undefined): boolean {
  const s = String(text || "").trim();
  if (!s) return false;
  if (/^error\b/i.test(s)) return true;
  if (/^\[L1\]\s+fail\b/i.test(s)) return true;
  if (/\bphase=error\b/i.test(s)) return true;
  // Counters like harness tqdm `error=0` are healthy progress — only non-zero / non-empty.
  if (/\berror\s*[=:]\s*(?!0\b)\S+/i.test(s)) return true;
  if (/\bcheckout failed\b/i.test(s)) return true;
  if (/\b(tool|turn)\.failed\b/i.test(s)) return true;
  if (/\btraceback\b/i.test(s)) return true;
  if (/\bexception\b/i.test(s)) return true;
  // Trailing / mid-line failure markers from ops / L1 emitters.
  if (/\bfailed:\s/i.test(s)) return true;
  if (/\bfailed\b/i.test(s) && /\b(error|exc|exception)\b/i.test(s)) return true;
  return false;
}
