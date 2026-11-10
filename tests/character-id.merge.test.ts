import { describe, expect, it } from "vitest";
import { mergeCharacterId } from "@/lib/character-id";

describe("mergeCharacterId", () => {
  it("lets an explicit null clear a stored id", () => {
    expect(mergeCharacterId(null, "char-1")).toBeNull();
  });

  it("keeps the stored id only when the incoming field is absent", () => {
    expect(mergeCharacterId(undefined, "char-1")).toBe("char-1");
    expect(mergeCharacterId(undefined, null)).toBeNull();
    expect(mergeCharacterId(undefined, undefined)).toBeUndefined();
  });

  it("takes a new id over the stored one", () => {
    expect(mergeCharacterId("char-2", "char-1")).toBe("char-2");
    expect(mergeCharacterId("char-2", null)).toBe("char-2");
    expect(mergeCharacterId("char-2", undefined)).toBe("char-2");
  });
});
