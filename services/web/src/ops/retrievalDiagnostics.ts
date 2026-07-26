/** Client-side diagnostics for retrieval audit layers (Ops only; no runtime impact). */

export type AuditHitLike = {
  chunk_id?: string;
  path?: string;
  truncated?: boolean;
};

export type AuditLike = {
  rank_method?: string | null;
  recall_pool?: AuditHitLike[];
  ranked?: AuditHitLike[];
  entered_context?: AuditHitLike[];
} | null;

export type RetrievalDiag = {
  id: string;
  level: "info" | "warn";
  message: string;
};

function hitKey(h: AuditHitLike): string {
  return (h.chunk_id || h.path || "").trim();
}

function idSet(rows: AuditHitLike[] | undefined): Set<string> {
  const s = new Set<string>();
  for (const h of rows || []) {
    const k = hitKey(h);
    if (k) s.add(k);
  }
  return s;
}

function sameOrderedKeys(a: AuditHitLike[], b: AuditHitLike[]): boolean {
  if (a.length !== b.length || a.length === 0) return false;
  for (let i = 0; i < a.length; i++) {
    if (hitKey(a[i]) !== hitKey(b[i])) return false;
  }
  return true;
}

/** Diff keys present in `from` but not in `to`. */
export function layerOnlyIn(
  from: AuditHitLike[] | undefined,
  to: AuditHitLike[] | undefined,
): string[] {
  const b = idSet(to);
  const out: string[] = [];
  for (const k of idSet(from)) {
    if (!b.has(k)) out.push(k);
  }
  return out;
}

export function diagnoseRetrievalAudit(audit: AuditLike, finalHits?: AuditHitLike[]): RetrievalDiag[] {
  const diags: RetrievalDiag[] = [];
  if (!audit) {
    diags.push({
      id: "no-audit",
      level: "warn",
      message: "无 audit 三层字段（旧事件或未传播）；仅能看最终 hits。",
    });
    return diags;
  }

  const l1 = audit.recall_pool ?? [];
  const l2 = audit.ranked ?? [];
  const l3 = audit.entered_context ?? [];
  const method = (audit.rank_method || "").toLowerCase();

  if (!l1.length && (l3.length || (finalHits && finalHits.length))) {
    diags.push({
      id: "empty-l1",
      level: "warn",
      message: "L1 recall_pool 为空但有最终命中——可能只记了进窗层。",
    });
  }

  if (
    method.includes("hybrid") &&
    sameOrderedKeys(l1, l2) &&
    sameOrderedKeys(l2, l3) &&
    l1.length > 0
  ) {
    diags.push({
      id: "isomorphic-hybrid",
      level: "warn",
      message:
        "rank_method 含 hybrid 且三层 chunk 同序同构——曾是审计未采到中间态的坑；请核对实现/版本。",
    });
  }

  if (l3.length > 0 && l3.every((h) => h.truncated)) {
    diags.push({
      id: "all-truncated",
      level: "info",
      message: "L3 全部 marked truncated——进窗摘录可能过短，坏例先查截断。",
    });
  }

  const droppedRank = layerOnlyIn(l1, l2);
  const droppedContext = layerOnlyIn(l2, l3);
  if (droppedRank.length) {
    diags.push({
      id: "dropped-rank",
      level: "info",
      message: `排序丢掉 ${droppedRank.length} 条（在 L1 不在 L2）。`,
    });
  }
  if (droppedContext.length) {
    diags.push({
      id: "dropped-context",
      level: "info",
      message: `进窗丢掉 ${droppedContext.length} 条（在 L2 不在 L3）。`,
    });
  }

  return diags;
}
