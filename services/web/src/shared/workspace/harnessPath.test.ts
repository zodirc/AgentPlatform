import { describe, expect, it } from "vitest";
import {
  isContinuityPendingPath,
  isHarnessInternalPath,
  isWorkSurfaceHiddenPath,
} from "./harnessPath";

describe("isHarnessInternalPath", () => {
  it("matches .agent root and children", () => {
    expect(isHarnessInternalPath(".agent")).toBe(true);
    expect(isHarnessInternalPath(".agent/work/drafts/manuscript.md")).toBe(
      true,
    );
    expect(isHarnessInternalPath("/.agent/verify-reports/x.md")).toBe(true);
  });

  it("does not match user deliverables", () => {
    expect(isHarnessInternalPath("manuscript.md")).toBe(false);
    expect(isHarnessInternalPath("exports/out.md")).toBe(false);
    expect(isHarnessInternalPath("drafts/note.md")).toBe(false);
    expect(isHarnessInternalPath(".")).toBe(false);
  });
});

describe("isContinuityPendingPath", () => {
  it("matches WN1 pending cards only", () => {
    expect(isContinuityPendingPath("sources/cards/pending")).toBe(true);
    expect(isContinuityPendingPath("sources/cards/pending/hero.md")).toBe(
      true,
    );
    expect(isContinuityPendingPath("sources/cards/hero.md")).toBe(false);
    expect(isContinuityPendingPath("sources/note.md")).toBe(false);
  });
});

describe("isWorkSurfaceHiddenPath", () => {
  it("covers harness and pending cards", () => {
    expect(isWorkSurfaceHiddenPath(".agent/work")).toBe(true);
    expect(isWorkSurfaceHiddenPath("sources/cards/pending/x.md")).toBe(true);
    expect(isWorkSurfaceHiddenPath("manuscript.md")).toBe(false);
  });
});
