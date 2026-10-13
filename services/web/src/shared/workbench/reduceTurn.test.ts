import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { reduceTurn, type TurnEnvelope } from "./reduceTurn";

const fixtures = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../../../../packages/contracts/tests/fixtures/turns",
);

describe("reduceTurn fixtures", () => {
  for (const name of readdirSync(fixtures).filter((item) => item.endsWith(".json"))) {
    it(name, () => {
      const raw = JSON.parse(readFileSync(join(fixtures, name), "utf8")) as {
        events: TurnEnvelope[];
        view: Record<string, unknown>;
      };
      expect(reduceTurn(raw.events)).toEqual(raw.view);
    });
  }
});
