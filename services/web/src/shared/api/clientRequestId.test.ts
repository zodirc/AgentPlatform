import { describe, expect, it, vi } from "vitest";

import { newClientRequestId } from "./clientRequestId";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

describe("newClientRequestId", () => {
  it("uses crypto.randomUUID when present", () => {
    const spy = vi.fn(() => "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee");
    vi.stubGlobal("crypto", { randomUUID: spy });
    expect(newClientRequestId()).toBe("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee");
    expect(spy).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });

  it("falls back when randomUUID is missing (HTTP LAN / old browsers)", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (buf: Uint8Array) => {
        buf.fill(7);
        return buf;
      },
    });
    const id = newClientRequestId();
    expect(id).toMatch(UUID_RE);
    vi.unstubAllGlobals();
  });
});
