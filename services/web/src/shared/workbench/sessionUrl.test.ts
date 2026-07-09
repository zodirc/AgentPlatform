import { describe, expect, it } from "vitest";
import {
  isSessionId,
  pathWithSession,
  sessionIdFromPathname,
  sessionIdFromSearch,
  shareableSessionPath,
} from "./sessionUrl";

const SAMPLE =
  "00000000-0000-0000-0000-000000000001";

describe("sessionUrl", () => {
  it("validates session uuid", () => {
    expect(isSessionId(SAMPLE)).toBe(true);
    expect(isSessionId("not-a-uuid")).toBe(false);
  });

  it("reads session from search params", () => {
    expect(sessionIdFromSearch(`?session=${SAMPLE}`)).toBe(SAMPLE);
    expect(sessionIdFromSearch("?session=bad")).toBeNull();
  });

  it("reads session from /s/ path", () => {
    expect(sessionIdFromPathname(`/s/${SAMPLE}`)).toBe(SAMPLE);
    expect(sessionIdFromPathname("/writing")).toBeNull();
  });

  it("builds path with session query", () => {
    expect(pathWithSession("/writing", SAMPLE)).toBe(
      `/writing?session=${SAMPLE}`,
    );
    expect(pathWithSession("/agent", null)).toBe("/agent");
  });

  it("builds shareable short path", () => {
    expect(shareableSessionPath(SAMPLE)).toBe(`/s/${SAMPLE}`);
  });
});
