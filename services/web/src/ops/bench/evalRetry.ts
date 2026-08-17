import type { ArtifactCase, SuiteId } from "./types";

/** Map a child-suite artifact key to the Ops start-run suite id. */
export function suiteIdForRetry(raw: string | undefined): SuiteId | null {
  const s = String(raw || "").toLowerCase();
  if (s.includes("coding") || s.includes("swebench")) return "coding";
  if (s.includes("retrieval_zh") || s.includes("cmteb")) return "retrieval_zh";
  if (s.includes("retrieval") || s.includes("beir")) return "retrieval";
  if (s.includes("context") || s.includes("longbench")) return "context";
  return null;
}

export function codingCaseNeedsRetry(c: ArtifactCase): boolean {
  if (c.resolved === true || c.resolve_verdict === "passed") return false;
  if (
    c.resolved === false ||
    c.resolve_verdict === "failed" ||
    c.resolve_verdict === "no_patch"
  ) {
    return true;
  }
  if (c.status === "fail") return true;
  const bucket = String(c.bucket || "");
  return Boolean(bucket && bucket !== "ok");
}

export function retrievalCaseNeedsRetry(c: ArtifactCase): boolean {
  if (c.status === "fail") return true;
  const recall = c.metrics?.recall_at_100;
  if (typeof recall === "number" && recall <= 0) return true;
  const ndcg = c.metrics?.ndcg_at_10;
  if (typeof ndcg === "number" && ndcg <= 0) return true;
  const bucket = String(c.bucket || "");
  return Boolean(bucket && bucket !== "ok");
}

export function contextCaseNeedsRetry(c: ArtifactCase): boolean {
  if (c.status === "fail") return true;
  const f1 = c.metrics?.f1 ?? c.metrics?.agent_f1;
  if (typeof f1 === "number" && f1 <= 0) return true;
  const bucket = String(c.bucket || "");
  return Boolean(bucket && bucket !== "ok");
}

export function artifactCaseNeedsRetry(
  suiteKey: string | undefined,
  c: ArtifactCase,
): boolean {
  if (!c.case_id) return false;
  if (String(c.case_id).endsWith(".agent")) return false;
  const suite = suiteIdForRetry(suiteKey);
  if (suite === "coding") return codingCaseNeedsRetry(c);
  if (suite === "retrieval" || suite === "retrieval_zh") {
    return retrievalCaseNeedsRetry(c);
  }
  if (suite === "context") return contextCaseNeedsRetry(c);
  return c.status === "fail";
}

/** SWE-bench Lite full; keep in sync with API MAX_RETRY_CASE_IDS. */
export const MAX_RETRY_CASE_IDS = 300;

export type FailedRetryPlan = {
  suites: SuiteId[];
  caseIds: string[];
};

/** Collect official-failed / error cases for a one-click retry run. */
export function failedRetryPlanFromArtifacts(
  data: { suites?: Array<{ suite?: string; cases?: ArtifactCase[] }> } | null | undefined,
  opts?: { suiteKey?: string },
): FailedRetryPlan {
  const caseIds: string[] = [];
  const seen = new Set<string>();
  const suites: SuiteId[] = [];
  const suiteSeen = new Set<SuiteId>();
  const filter = opts?.suiteKey;
  for (const suite of data?.suites || []) {
    const sid = suiteIdForRetry(suite.suite);
    if (!sid) continue;
    if (
      filter &&
      suite.suite !== filter &&
      suiteIdForRetry(filter) !== sid
    ) {
      continue;
    }
    for (const c of suite.cases || []) {
      const id = String(c.case_id || "").trim();
      if (!id || seen.has(id)) continue;
      if (!artifactCaseNeedsRetry(suite.suite, c)) continue;
      seen.add(id);
      caseIds.push(id);
      if (!suiteSeen.has(sid)) {
        suiteSeen.add(sid);
        suites.push(sid);
      }
    }
  }
  return { suites, caseIds };
}
