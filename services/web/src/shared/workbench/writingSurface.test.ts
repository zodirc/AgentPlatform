import { describe, expect, it } from "vitest";
import {
  patchCandidateFromPayload,
  pinnedCardsFromPayload,
  selectWhileRunning,
} from "./writingSurface";

describe("writingSurface", () => {
  it("reads a patch.proposed payload", () => {
    expect(
      patchCandidateFromPayload({
        patch_id: "patch-1",
        path: "outline.md",
        old_text: "旧",
        new_text: "新",
        status: "pending",
      })?.patch_id,
    ).toBe("patch-1");
    expect(patchCandidateFromPayload({ path: "outline.md" })).toBeNull();
  });

  it("reads a cards.pinned payload", () => {
    const pinned = pinnedCardsFromPayload({
      cards: [{ title: "秦禹", kind: "character" }],
      available_count: 2,
    });
    expect(pinned?.type).toBe("writing_cards");
    expect(pinned?.cards).toHaveLength(1);
  });

  it("prefers the event projection while a turn is running", () => {
    const chosen = selectWhileRunning(
      true,
      [{ patch_id: "live" }],
      [{ patch_id: "server" }],
      (rows) => rows.length === 0,
    );
    expect(chosen?.[0].patch_id).toBe("live");
  });

  it("prefers the server view after the turn ends", () => {
    const chosen = selectWhileRunning(
      false,
      [{ patch_id: "live" }],
      [{ patch_id: "server" }],
      (rows) => rows.length === 0,
    );
    expect(chosen?.[0].patch_id).toBe("server");
  });
});
