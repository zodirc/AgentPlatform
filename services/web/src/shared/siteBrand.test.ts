import { describe, expect, it } from "vitest";
import {
  formatDocumentTitle,
  isOpsPath,
  siteBrandForPath,
  SITE_APP,
  SITE_OPS,
} from "./siteBrand";

describe("siteBrand", () => {
  it("routes ops paths to Ops brand", () => {
    expect(isOpsPath("/ops/secret/test")).toBe(true);
    expect(siteBrandForPath("/ops/x/retrieval").name).toBe(SITE_OPS.name);
    expect(siteBrandForPath("/writing").name).toBe(SITE_APP.name);
  });

  it("formats document titles", () => {
    expect(formatDocumentTitle(SITE_APP)).toBe("Agent Platform");
    expect(formatDocumentTitle(SITE_OPS, "评测历史")).toBe("评测历史 · Ops 评测台");
  });
});
