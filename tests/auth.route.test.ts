/* @vitest-environment node */

import { describe, expect, it } from "vitest";
import { GET, POST } from "@/app/api/auth/[...nextauth]/route";

describe("auth route handler", () => {
  it("exports public auth handlers", () => {
    expect(GET).toBeTypeOf("function");
    expect(POST).toBeTypeOf("function");
  });
});
