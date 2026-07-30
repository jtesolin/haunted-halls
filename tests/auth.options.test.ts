/* @vitest-environment node */

import { describe, expect, it } from "vitest";
import { authOptions } from "@/lib/auth";

describe("auth options", () => {
  it("rejects unsafe external callback destinations", async () => {
    const redirect = authOptions.callbacks?.redirect;
    expect(redirect).toBeTypeOf("function");

    if (!redirect) {
      throw new Error("redirect callback is not configured");
    }

    const safe = await redirect({
      url: "/campaign",
      baseUrl: "https://haunted-halls.example",
    });
    const unsafe = await redirect({
      url: "https://evil.example/steal",
      baseUrl: "https://haunted-halls.example",
    });

    expect(safe).toBe("https://haunted-halls.example/campaign");
    expect(unsafe).toBe("https://haunted-halls.example");
  });

  it("exposes jwt and session callbacks for internal user resolution", () => {
    expect(authOptions.callbacks?.jwt).toBeTypeOf("function");
    expect(authOptions.callbacks?.session).toBeTypeOf("function");
  });
});
