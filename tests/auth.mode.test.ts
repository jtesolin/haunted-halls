/* @vitest-environment node */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("server auth modes", () => {
  beforeEach(() => {
    vi.stubEnv("E2E_AUTH_ENABLED", "");
    vi.stubEnv("GOOGLE_CLIENT_ID", "test-client");
    vi.stubEnv("GOOGLE_CLIENT_SECRET", "test-secret");
    vi.resetModules();
  });
  afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); });

  it.each([undefined, "google"])("preserves Google mode %s", async (mode) => {
    vi.stubEnv("AUTH_MODE", mode);
    const { authOptions } = await import("@/lib/auth");
    expect(authOptions.providers.map(provider => provider.id)).toEqual(["google"]);
  });

  it.each(["", "unknown", "IAP"])("fails closed for explicit mode %j", async (mode) => {
    vi.stubEnv("AUTH_MODE", mode);
    await expect(import("@/lib/auth")).rejects.toThrow("AUTH_MODE");
  });

  it("requires the existing flag in explicit E2E mode", async () => {
    vi.stubEnv("AUTH_MODE", "e2e");
    await expect(import("@/lib/auth")).rejects.toThrow("E2E_AUTH_ENABLED");
  });

  it.each([undefined, "https://preview.example.com"])("refuses E2E outside loopback %s", async (url) => {
    vi.stubEnv("AUTH_MODE", "e2e");
    vi.stubEnv("E2E_AUTH_ENABLED", "true");
    vi.stubEnv("NEXTAUTH_URL", url);
    await expect(import("@/lib/auth")).rejects.toThrow("loopback");
  });

  it("registers only E2E when explicitly enabled on loopback", async () => {
    vi.stubEnv("AUTH_MODE", "e2e");
    vi.stubEnv("E2E_AUTH_ENABLED", "true");
    vi.stubEnv("NEXTAUTH_URL", "http://localhost:3000");
    const { authOptions } = await import("@/lib/auth");
    expect(authOptions.providers).toHaveLength(1);
    expect(authOptions.providers[0].options?.id).toBe("e2e");
  });
});
