import { describe, expect, it } from "vitest";

import { describeMetric, metricLeaf } from "./metricGlossary";

describe("metricLeaf", () => {
  it("strips official suite and agent prefixes", () => {
    expect(metricLeaf("official.retrieval_zh.ndcg_at_10")).toBe("ndcg_at_10");
    expect(metricLeaf("official.coding_infer.resolve_rate")).toBe(
      "resolve_rate",
    );
    expect(metricLeaf("official.context.agent_f1")).toBe("agent_f1");
  });
});

describe("describeMetric", () => {
  it("names resolve_rate in Chinese and flags smoke vs anchor", () => {
    const info = describeMetric("official.coding_infer.resolve_rate");
    expect(info.zh).toBe("官方解决率");
    expect(info.en).toMatch(/FAIL/i);
    expect(info.effect).toMatch(/n25/);
  });

  it("marks BEIR R@100 as first retrieval gate", () => {
    const info = describeMetric("official.retrieval.recall_at_100");
    expect(info.zh).toContain("召回");
    expect(info.effect).toMatch(/第一验收/);
    expect(info.effect).toMatch(/BEIR/);
  });

  it("labels C-MTEB separately from BEIR", () => {
    const zh = describeMetric("official.retrieval_zh.ndcg_at_10");
    const en = describeMetric("official.retrieval.ndcg_at_10");
    expect(zh.scope).toBe("中文检索 C-MTEB");
    expect(en.scope).toBe("英文检索 BEIR");
    expect(zh.zh).toBe(en.zh);
  });

  it("names F1 as word overlap, not token jargon", () => {
    const info = describeMetric("official.context.agent_f1");
    expect(info.zh).toBe("用词重合 F1");
    expect(info.zh).not.toMatch(/词元/);
    expect(info.effect).toMatch(/按空格拆成词/);
    expect(info.effect).toMatch(/意思近/);
  });

  it("explains nDCG as ranked position, not a hit/miss", () => {
    const info = describeMetric("official.retrieval.ndcg_at_10");
    expect(info.zh).toMatch(/前10名排位/);
    expect(info.en).toMatch(/Discounted Cumulative Gain/i);
    expect(info.effect).toMatch(/第 1 名=1/);
    expect(info.effect).toMatch(/第 10 名/);
  });

  it("explains patch-no-apply as apply failure, not test failure", () => {
    const info = describeMetric(
      "official.coding_infer.bucket_share_patch_no_apply",
    );
    expect(info.zh).toMatch(/打不上/);
    expect(info.effect).toMatch(/git apply/);
    expect(info.effect).toMatch(/测试没过/);
  });

  it("explains no_ws_symbol as missing definition name, not a broken index", () => {
    const info = describeMetric(
      "official.coding_infer.n_locate_fuse_no_ws_symbol",
    );
    expect(info.zh).toMatch(/没有这个符号/);
    expect(info.effect).toMatch(/索引只收/);
    expect(info.effect).not.toMatch(/官方效果/);
  });
});
