// Test-only NextAuth authentication seam for full-stack Playwright E2E coverage.
//
// SAFETY: This provider must never be reachable outside a loopback development/test
// environment. It is gated on a server-side-only flag (E2E_AUTH_ENABLED) combined with
// a strict loopback check on NEXTAUTH_URL. It must never rely on a client-side/public
// environment variable, and it must fail closed (throw a configuration error) rather
// than silently disable itself if misconfigured, so a misconfigured production deploy
// cannot accidentally expose it.
//
// The provider accepts no browser-supplied identity fields. It always resolves the
// same fixed synthetic identity through the existing resolveInternalUserId() /
// buildGoogleIdentityProfile() engine-user-resolution path, so the E2E suite exercises
// a real engine-owned internal user id rather than a client-forged one.

const LOOPBACK_HOSTNAMES = new Set(["localhost", "127.0.0.1", "::1"]);

export const E2E_PROVIDER_ID = "e2e";

export const E2E_FIXED_IDENTITY = {
  identityProvider: "google" as const,
  providerIssuer: "https://accounts.google.com",
  providerSubject: "playwright-e2e",
  email: "playwright-e2e@example.com",
  emailVerified: true as const,
  displayName: "Playwright Test User",
  avatarUrl: null,
};

export class E2EAuthConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "E2EAuthConfigurationError";
  }
}

function isLoopbackOrigin(rawUrl: string | undefined): boolean {
  if (!rawUrl) {
    return false;
  }

  try {
    const url = new URL(rawUrl);
    return LOOPBACK_HOSTNAMES.has(url.hostname);
  } catch {
    return false;
  }
}

/**
 * Determines whether the test-only E2E credentials provider is allowed to be
 * registered/enabled for this process.
 *
 * Both conditions are required:
 *  - the server-side-only E2E_AUTH_ENABLED flag is explicitly "true"
 *  - NEXTAUTH_URL is a loopback origin (http://localhost:3000, http://127.0.0.1:3000, etc.)
 *
 * If E2E_AUTH_ENABLED is set but NEXTAUTH_URL is missing/invalid/non-loopback, this
 * throws rather than returning false, so misconfiguration fails closed at startup
 * instead of silently exposing (or silently disabling) the seam.
 */
export function isE2EAuthEnabled(): boolean {
  const flagRaw = process.env.E2E_AUTH_ENABLED?.trim().toLowerCase();
  const flagEnabled = flagRaw === "true";

  if (!flagEnabled) {
    return false;
  }

  const nextAuthUrl = process.env.NEXTAUTH_URL?.trim();
  if (!isLoopbackOrigin(nextAuthUrl)) {
    throw new E2EAuthConfigurationError(
      "E2E_AUTH_ENABLED is set but NEXTAUTH_URL is not a loopback development/test origin. " +
        "Refusing to start rather than risk exposing the test-only authentication seam."
    );
  }

  return true;
}
