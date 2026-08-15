import { describe, expect, it } from "vitest";

import { dropAliasedMetrics, runMetrics } from "./metrics";
import type { OfficialRun } from "./types";

describe("dropAliasedMetrics", () => {
  it("drops agent.* when the unprefixed twin has the same value", () => {
    expect(
      dropAliasedMetrics({
        "official.retrieval_zh.recall_at_10": 0.8167,
        "official.retrieval_zh.agent.recall_at_10": 0.8167,
        "official.retrieval_zh.ndcg_at_10": 0.6963,
        "official.retrieval_zh.agent.ndcg_at_10": 0.6963,
      }),
    ).toEqual({
      "official.retrieval_zh.recall_at_10": 0.8167,
      "official.retrieval_zh.ndcg_at_10": 0.6963,
    });
  });

  it("keeps agent.* when there is no twin (legacy-only keys)", () => {
    expect(dropAliasedMetrics({ "agent.ndcg_at_10": 0.4 })).toEqual({
      "agent.ndcg_at_10": 0.4,
    });
  });

  it("keeps dataset rollup keys that only exist under *.agent", () => {
    expect(
      dropAliasedMetrics({
        "cmteb.T2Retrieval.agent.recall_at_10": 0.9,
      }),
    ).toEqual({
      "cmteb.T2Retrieval.agent.recall_at_10": 0.9,
    });
  });

  it("keeps both when values differ", () => {
    expect(
      dropAliasedMetrics({
        ndcg_at_10: 0.4,
        "agent.ndcg_at_10": 0.403,
      }),
    ).toEqual({
      ndcg_at_10: 0.4,
      "agent.ndcg_at_10": 0.403,
    });
  });
});

describe("runMetrics", () => {
  it("flattens official.retrieval_zh without duplicated agent.* copies", () => {
    const run = {
      cases: [
        {
          case_id: "official.retrieval_zh",
          metrics: {
            recall_at_10: 0.8,
            "agent.recall_at_10": 0.8,
            n_queries: 20,
          },
        },
      ],
    } as OfficialRun;
    expect(runMetrics(run)).toEqual({
      "official.retrieval_zh.recall_at_10": 0.8,
      "official.retrieval_zh.n_queries": 20,
    });
  });
});
