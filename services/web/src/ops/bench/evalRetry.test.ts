import { describe, expect, it } from "vitest";

import {
  artifactCaseNeedsRetry,
  codingCaseNeedsRetry,
  failedRetryPlanFromArtifacts,
  suiteIdForRetry,
} from "./evalRetry";

describe("suiteIdForRetry", () => {
  it("maps artifact suite keys", () => {
    expect(suiteIdForRetry("coding_infer")).toBe("coding");
    expect(suiteIdForRetry("swebench_lite")).toBe("coding");
    expect(suiteIdForRetry("retrieval")).toBe("retrieval");
    expect(suiteIdForRetry("cmteb.small")).toBe("retrieval_zh");
    expect(suiteIdForRetry("context")).toBe("context");
  });
});

describe("codingCaseNeedsRetry", () => {
  it("skips harness-resolved cases", () => {
    expect(codingCaseNeedsRetry({ resolved: true, status: "pass" })).toBe(
      false,
    );
  });

  it("retries unresolved and failed-turn cases", () => {
    expect(codingCaseNeedsRetry({ resolved: false, status: "pass" })).toBe(
      true,
    );
    expect(
      codingCaseNeedsRetry({
        status: "fail",
        bucket: "turn_failed",
        resolved: null,
      }),
    ).toBe(true);
  });
});

describe("artifactCaseNeedsRetry", () => {
  it("ignores dataset rollup rows", () => {
    expect(
      artifactCaseNeedsRetry("retrieval", {
        case_id: "beir.scifact.agent",
        status: "fail",
      }),
    ).toBe(false);
  });
});

describe("failedRetryPlanFromArtifacts", () => {
  it("collects unresolved coding and failed retrieval, skips rollups", () => {
    const plan = failedRetryPlanFromArtifacts({
      suites: [
        {
          suite: "coding_infer",
          cases: [
            { case_id: "astropy__astropy-14182", resolved: true, status: "pass" },
            { case_id: "astropy__astropy-14365", resolved: false, status: "pass" },
            {
              case_id: "astropy__astropy-12907",
              status: "fail",
              bucket: "turn_failed",
            },
          ],
        },
        {
          suite: "retrieval",
          cases: [
            { case_id: "beir.scifact.agent", status: "fail" },
            { case_id: "beir.scifact.q-1", status: "fail" },
            { case_id: "beir.scifact.q-2", status: "pass", bucket: "ok" },
          ],
        },
      ],
    });
    expect(plan.suites).toEqual(["coding", "retrieval"]);
    expect(plan.caseIds).toEqual([
      "astropy__astropy-14365",
      "astropy__astropy-12907",
      "beir.scifact.q-1",
    ]);
  });

  it("filters to one suite when suiteKey is set", () => {
    const plan = failedRetryPlanFromArtifacts(
      {
        suites: [
          {
            suite: "coding_infer",
            cases: [{ case_id: "astropy__astropy-14365", resolved: false }],
          },
          {
            suite: "retrieval",
            cases: [{ case_id: "beir.scifact.q-1", status: "fail" }],
          },
        ],
      },
      { suiteKey: "coding_infer" },
    );
    expect(plan.suites).toEqual(["coding"]);
    expect(plan.caseIds).toEqual(["astropy__astropy-14365"]);
  });
});
