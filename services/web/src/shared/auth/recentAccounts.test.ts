import { afterEach, describe, expect, it } from "vitest";
import {
  readRecentUsernames,
  rememberUsername,
} from "./recentAccounts";

const KEY = "agent.auth.recent_usernames";

afterEach(() => {
  localStorage.removeItem(KEY);
});

describe("recentAccounts", () => {
  it("remembers usernames MRU without duplicates", () => {
    rememberUsername("alice");
    rememberUsername("bob");
    rememberUsername("alice");
    expect(readRecentUsernames()).toEqual(["alice", "bob"]);
  });

  it("caps at five entries", () => {
    for (const name of ["a", "b", "c", "d", "e", "f"]) {
      rememberUsername(name);
    }
    expect(readRecentUsernames()).toEqual(["f", "e", "d", "c", "b"]);
  });
});
