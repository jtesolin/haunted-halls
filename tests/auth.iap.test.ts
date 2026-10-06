/* @vitest-environment node */

import { generateKeyPairSync, sign } from "node:crypto";
import { OAuth2Client } from "google-auth-library";
import type { CredentialsConfig } from "next-auth/providers/credentials";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { verifyIapIdentity, IAP_ISSUER } from "@/lib/iap-auth";
import { fetchEngineAsService } from "@/lib/engine";

vi.mock("@/lib/engine", () => ({
  fetchEngineAsService: vi.fn(),
  InternalEngineConfigurationError: class extends Error {},
  InternalEngineOriginError: class extends Error {},
}));

const audience = "/projects/123/locations/us-central1/services/preview-41";
const { privateKey, publicKey } = generateKeyPairSync("ec", { namedCurve: "prime256v1" });
const pubkeys = { test: publicKey.export({ type: "spki", format: "pem" }).toString() };
const now = Math.floor(Date.now() / 1000);

function assertion(overrides: Record<string, unknown> = {}, key = privateKey) {
  const header = Buffer.from(JSON.stringify({ alg: "ES256", kid: "test" })).toString("base64url");
  const payload = Buffer.from(JSON.stringify({
    iss: IAP_ISSUER, aud: audience, iat: now - 10, exp: now + 600,
    sub: "iap-subject", email: "player@example.com", ...overrides,
  })).toString("base64url");
  const input = `${header}.${payload}`;
  return `${input}.${sign("sha256", Buffer.from(input), { key, dsaEncoding: "ieee-p1363" }).toString("base64url")}`;
}

async function loadIapProvider() {
  const { authOptions } = await import("@/lib/auth");
  const provider = authOptions.providers[0];
  if (provider.type !== "credentials") throw new Error("Expected credentials provider");
  const config = { ...provider, ...provider.options } as CredentialsConfig;
  return { authOptions, config };
}

describe("IAP signed-header authentication", () => {
  beforeEach(() => {
    vi.stubEnv("AUTH_MODE", "iap");
    vi.stubEnv("IAP_EXPECTED_AUDIENCE", audience);
    vi.stubEnv("GOOGLE_CLIENT_ID", "");
    vi.stubEnv("GOOGLE_CLIENT_SECRET", "");
    vi.spyOn(OAuth2Client.prototype, "getIapPublicKeysAsync").mockResolvedValue({ pubkeys });
    vi.mocked(fetchEngineAsService).mockResolvedValue(new Response(JSON.stringify({ user_id: "internal-iap-user" })));
    vi.resetModules();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("registers only IAP without Google credentials even if the E2E flag is set", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXTAUTH_SECRET", "test-only-secret");
    vi.stubEnv("E2E_AUTH_ENABLED", "true");
    const { authOptions, config } = await loadIapProvider();
    expect(authOptions.providers).toHaveLength(1);
    expect(config.id).toBe("iap");
    expect(config.credentials).toEqual({});
  });

  it("fails closed without an audience", async () => {
    vi.stubEnv("IAP_EXPECTED_AUDIENCE", "");
    await expect(import("@/lib/auth")).rejects.toThrow("IAP_EXPECTED_AUDIENCE");
  });

  it("verifies with exact IAP keys, issuer, and audience", async () => {
    const verifier = vi.spyOn(OAuth2Client.prototype, "verifySignedJwtWithCertsAsync");
    const jwt = assertion();
    const identity = await verifyIapIdentity(jwt, audience);
    expect(verifier).toHaveBeenCalledWith(jwt, pubkeys, audience, [IAP_ISSUER]);
    expect(identity).toMatchObject({
      identityProvider: "google", providerIssuer: "https://accounts.google.com",
      providerSubject: "iap:iap-subject", email: "player@example.com", emailVerified: true,
    });
    expect(identity.providerSubject).not.toBe("iap-subject");
  });

  it.each([
    { aud: "wrong-audience" }, { iss: "https://accounts.google.com" },
    { exp: now - 600 }, { iat: now + 600 }, { iat: undefined }, { exp: undefined },
    { nbf: now + 600 }, { nbf: "invalid" }, { exp: now - 20 },
    { sub: undefined }, { sub: "" }, { sub: "  " }, { sub: 123 },
    { email: undefined }, { email: "" }, { email: "invalid" }, { email: 123 },
  ])("rejects invalid signed claims %j", async (claims) => {
    await expect(verifyIapIdentity(assertion(claims), audience)).rejects.toThrow("IAP authentication failed");
    expect(fetchEngineAsService).not.toHaveBeenCalled();
  });

  it("rejects an invalid signature without exposing the assertion", async () => {
    const other = generateKeyPairSync("ec", { namedCurve: "prime256v1" });
    await expect(verifyIapIdentity(assertion({}, other.privateKey), audience)).rejects.toThrow(/^IAP authentication failed$/);
  });

  it("rejects malformed assertions", async () => {
    await expect(verifyIapIdentity("not-a-jwt", audience)).rejects.toThrow(/^IAP authentication failed$/);
  });

  it("fails closed when public keys are unavailable", async () => {
    vi.mocked(OAuth2Client.prototype.getIapPublicKeysAsync).mockRejectedValue(new Error("unavailable"));
    await expect(verifyIapIdentity(assertion(), audience)).rejects.toThrow(/^IAP authentication failed$/);
    expect(fetchEngineAsService).not.toHaveBeenCalled();
  });

  it("rejects engine resolution failure with a sanitized error", async () => {
    vi.mocked(fetchEngineAsService).mockResolvedValue(new Response("unavailable", { status: 503 }));
    const { config } = await loadIapProvider();
    vi.spyOn(console, "error").mockImplementation(() => {});
    await expect(config.authorize({}, { headers: { "x-goog-iap-jwt-assertion": assertion() } })).rejects.toThrow(/^AccessDenied$/);
  });

  it("rejects missing assertion and unsigned identity headers, ignoring credentials", async () => {
    const { config } = await loadIapProvider();
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    await expect(config.authorize({}, { headers: {} })).rejects.toThrow("AccessDenied");
    await expect(config.authorize(
      { email: "forged@example.com", sub: "forged" },
      { headers: { "x-goog-authenticated-user-email": "accounts.google.com:forged@example.com", "x-goog-authenticated-user-id": "forged" } }
    )).rejects.toThrow("AccessDenied");
    expect(fetchEngineAsService).not.toHaveBeenCalled();
    expect(OAuth2Client.prototype.getIapPublicKeysAsync).not.toHaveBeenCalled();
    expect(log).toHaveBeenCalledWith("iap auth sign-in failed during verification or internal user resolution");
  });

  it("resolves verified identity and carries internalUserId through JWT and session", async () => {
    const { config, authOptions } = await loadIapProvider();
    const user = await config.authorize(
      { email: "forged@example.com", sub: "forged", internalUserId: "forged" },
      { headers: { "x-goog-iap-jwt-assertion": assertion() } }
    );
    expect(user).toMatchObject({ id: "iap:iap-subject", internalUserId: "internal-iap-user" });
    const [, init] = vi.mocked(fetchEngineAsService).mock.calls[0];
    expect(JSON.parse(String(init?.body))).toMatchObject({
      identity_provider: "google", provider_issuer: "https://accounts.google.com",
      provider_subject: "iap:iap-subject", email: "player@example.com", email_verified: true,
    });
    if (!user || !authOptions.callbacks?.jwt || !authOptions.callbacks.session) throw new Error("Missing callbacks");
    const token = await authOptions.callbacks.jwt({
      token: {}, user, account: { provider: "iap", type: "credentials", providerAccountId: user.id },
      isNewUser: false, trigger: "signIn",
    });
    expect(token.internalUserId).toBe("internal-iap-user");
    expect(token.authMode).toBe("iap");
    const session = await authOptions.callbacks.session({
      session: { expires: "2099-01-01", user: { name: null, email: user.email ?? null, image: null } },
      token, user: { ...user, email: user.email ?? "", emailVerified: null },
      newSession: undefined, trigger: "update",
    });
    expect(session).toHaveProperty("internalUserId", "internal-iap-user");
  });
});
