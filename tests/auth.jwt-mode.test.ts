/* @vitest-environment node */

import type { JWT } from "next-auth/jwt";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/engine", () => ({
  fetchEngineAsService: vi.fn(),
  InternalEngineConfigurationError: class extends Error {},
  InternalEngineOriginError: class extends Error {},
}));

async function reuse(token: JWT) {
  const { authOptions } = await import("@/lib/auth");
  if (!authOptions.callbacks?.jwt) throw new Error("Missing JWT callback");
  return authOptions.callbacks.jwt({
    token, account: null, user: { id: "test" },
    trigger: "update", session: undefined,
  });
}

describe("persisted JWT auth-mode binding", () => {
  beforeEach(() => {
    vi.stubEnv("AUTH_MODE", "google");
    vi.stubEnv("IAP_EXPECTED_AUDIENCE", "/projects/123/locations/us-east1/services/preview");
    vi.stubEnv("E2E_AUTH_ENABLED", "true");
    vi.stubEnv("NEXTAUTH_URL", "http://localhost:3000");
    vi.resetModules();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it.each(["google", "iap", "e2e"] as const)("reuses same-mode %s tokens", async (mode) => {
    vi.stubEnv("AUTH_MODE", mode);
    const token: JWT = { internalUserId: "internal-user", authMode: mode };
    if (mode === "e2e") token.e2eAuth = true;
    await expect(reuse(token)).resolves.toBe(token);
  });

  it.each([
    ["google", "iap"], ["google", "e2e"], ["iap", "google"],
    ["iap", "e2e"], ["e2e", "google"], ["e2e", "iap"],
  ] as const)("rejects %s tokens in %s mode", async (issued, current) => {
    vi.stubEnv("AUTH_MODE", current);
    await expect(reuse({
      internalUserId: "internal-user", authMode: issued,
      ...(issued === "e2e" ? { e2eAuth: true as const } : {}),
    })).rejects.toThrow("AccessDenied");
  });

  it("accepts and stamps legacy unmarked Google sessions", async () => {
    const token = { internalUserId: "legacy-user" };
    await expect(reuse(token)).resolves.toMatchObject({ ...token, authMode: "google" });
  });

  it.each(["iap", "e2e"])("rejects legacy unmarked sessions in %s", async (mode) => {
    vi.stubEnv("AUTH_MODE", mode);
    await expect(reuse({ internalUserId: "legacy-user" })).rejects.toThrow("AccessDenied");
  });

  it("rejects legacy E2E tokens even in Google mode", async () => {
    await expect(reuse({ internalUserId: "legacy-user", e2eAuth: true })).rejects.toThrow("AccessDenied");
  });

  it.each(["disabled", "non-loopback"])("still enforces the E2E guard: %s", async (failure) => {
    vi.stubEnv("AUTH_MODE", "e2e");
    const token: JWT = { internalUserId: "internal-user", authMode: "e2e", e2eAuth: true };
    await reuse(token);
    if (failure === "disabled") vi.stubEnv("E2E_AUTH_ENABLED", "false");
    else vi.stubEnv("NEXTAUTH_URL", "https://preview.example.com");
    await expect(reuse(token)).rejects.toThrow("AccessDenied");
  });

  it("rejects E2E tokens missing the safety marker", async () => {
    vi.stubEnv("AUTH_MODE", "e2e");
    await expect(reuse({ internalUserId: "internal-user", authMode: "e2e" })).rejects.toThrow("AccessDenied");
  });
});
