/* @vitest-environment node */

import { afterEach, describe, expect, it } from "vitest";

const ORIGINAL_ENV = { ...process.env };

function resetEnv() {
  for (const key of Object.keys(process.env)) {
    if (!(key in ORIGINAL_ENV)) {
      delete process.env[key];
    }
  }
  Object.assign(process.env, ORIGINAL_ENV);
  delete process.env.E2E_AUTH_ENABLED;
  delete process.env.NEXTAUTH_URL;
}

describe("isE2EAuthEnabled", () => {
  afterEach(() => {
    resetEnv();
  });

  it("is disabled by default", async () => {
    const { isE2EAuthEnabled } = await import("@/lib/e2e-auth");
    delete process.env.E2E_AUTH_ENABLED;
    expect(isE2EAuthEnabled()).toBe(false);
  });

  it("stays disabled when flag is falsy", async () => {
    const { isE2EAuthEnabled } = await import("@/lib/e2e-auth");
    process.env.E2E_AUTH_ENABLED = "false";
    process.env.NEXTAUTH_URL = "http://localhost:3000";
    expect(isE2EAuthEnabled()).toBe(false);
  });

  it("enables when flag is true and NEXTAUTH_URL is loopback (localhost)", async () => {
    const { isE2EAuthEnabled } = await import("@/lib/e2e-auth");
    process.env.E2E_AUTH_ENABLED = "true";
    process.env.NEXTAUTH_URL = "http://localhost:3000";
    expect(isE2EAuthEnabled()).toBe(true);
  });

  it("enables when flag is true and NEXTAUTH_URL is loopback (127.0.0.1)", async () => {
    const { isE2EAuthEnabled } = await import("@/lib/e2e-auth");
    process.env.E2E_AUTH_ENABLED = "true";
    process.env.NEXTAUTH_URL = "http://127.0.0.1:3000";
    expect(isE2EAuthEnabled()).toBe(true);
  });

  it("fails closed (throws) when flag is true but NEXTAUTH_URL is the production canonical origin", async () => {
    const { isE2EAuthEnabled, E2EAuthConfigurationError } = await import("@/lib/e2e-auth");
    process.env.E2E_AUTH_ENABLED = "true";
    process.env.NEXTAUTH_URL = "https://haunted-halls.tesolin.us";
    expect(() => isE2EAuthEnabled()).toThrow(E2EAuthConfigurationError);
  });

  it("fails closed (throws) when flag is true but NEXTAUTH_URL is missing", async () => {
    const { isE2EAuthEnabled, E2EAuthConfigurationError } = await import("@/lib/e2e-auth");
    process.env.E2E_AUTH_ENABLED = "true";
    delete process.env.NEXTAUTH_URL;
    expect(() => isE2EAuthEnabled()).toThrow(E2EAuthConfigurationError);
  });

  it("fails closed (throws) when flag is true but NEXTAUTH_URL is invalid", async () => {
    const { isE2EAuthEnabled, E2EAuthConfigurationError } = await import("@/lib/e2e-auth");
    process.env.E2E_AUTH_ENABLED = "true";
    process.env.NEXTAUTH_URL = "not-a-url";
    expect(() => isE2EAuthEnabled()).toThrow(E2EAuthConfigurationError);
  });
});
