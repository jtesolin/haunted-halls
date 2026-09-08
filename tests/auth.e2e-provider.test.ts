/* @vitest-environment node */

import { afterEach, describe, expect, it, vi } from "vitest";

const ORIGINAL_ENV = { ...process.env };

function resetEnv() {
  for (const key of Object.keys(process.env)) {
    if (!(key in ORIGINAL_ENV)) {
      delete process.env[key];
    }
  }
  Object.assign(process.env, ORIGINAL_ENV);
  delete process.env.E2E_AUTH_ENABLED;
}

describe("authOptions e2e provider registration", () => {
  afterEach(() => {
    resetEnv();
    vi.resetModules();
  });

  function resolveProviderId(provider: { id: string; options?: unknown }) {
    const options = provider.options as { id?: string } | undefined;
    return options?.id ?? provider.id;
  }

  it("does not register the e2e provider by default", async () => {
    delete process.env.E2E_AUTH_ENABLED;
    vi.resetModules();
    const { authOptions } = await import("@/lib/auth");
    const providerIds = authOptions.providers.map(resolveProviderId);
    expect(providerIds).not.toContain("e2e");
  });

  it("registers the e2e provider only when guard is satisfied", async () => {
    process.env.E2E_AUTH_ENABLED = "true";
    process.env.NEXTAUTH_URL = "http://localhost:3000";
    vi.resetModules();
    const { authOptions } = await import("@/lib/auth");
    const providerIds = authOptions.providers.map(resolveProviderId);
    expect(providerIds).toContain("e2e");
  });

  it("throws at module load when guard flag is set with a non-loopback NEXTAUTH_URL", async () => {
    process.env.E2E_AUTH_ENABLED = "true";
    process.env.NEXTAUTH_URL = "https://haunted-halls.tesolin.us";
    vi.resetModules();
    await expect(import("@/lib/auth")).rejects.toThrow();
  });
});
