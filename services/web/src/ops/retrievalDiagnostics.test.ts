import { describe, expect, it } from "vitest";
import { diagnoseRetrievalAudit, layerOnlyIn } from "./retrievalDiagnostics";

describe("retrievalDiagnostics", () => {
  it("flags isomorphic hybrid layers", () => {
    const hit = { chunk_id: "c1", path: "a.md" };
    const diags = diagnoseRetrievalAudit({
      rank_method: "hybrid",
      recall_pool: [hit],
      ranked: [hit],
      entered_context: [hit],
    });
    expect(diags.some((d) => d.id === "isomorphic-hybrid")).toBe(true);
  });

  it("reports layer-only keys", () => {
    const only = layerOnlyIn(
      [{ chunk_id: "a" }, { chunk_id: "b" }],
      [{ chunk_id: "a" }],
    );
    expect(only).toEqual(["b"]);
  });

  it("flags all-truncated L3", () => {
    const diags = diagnoseRetrievalAudit({
      rank_method: "lexical",
      recall_pool: [{ chunk_id: "a" }],
      ranked: [{ chunk_id: "a" }],
      entered_context: [{ chunk_id: "a", truncated: true }],
    });
    expect(diags.some((d) => d.id === "all-truncated")).toBe(true);
  });
});
