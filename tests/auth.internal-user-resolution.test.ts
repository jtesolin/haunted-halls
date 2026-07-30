/* @vitest-environment node */

import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/engine", () => ({
  fetchEngine: vi.fn(),
  InternalEngineConfigurationError: class InternalEngineConfigurationError extends Error {},
  InternalEngineOriginError: class InternalEngineOriginError extends Error {},
}));

import type { AdapterUser } from "next-auth/adapters";
import { authOptions } from "@/lib/auth";
import {
  buildGoogleIdentityProfile,
  CANONICAL_GOOGLE_ISSUER,
  resolveInternalUserId,
} from "@/lib/internal-user-resolution";
import { fetchEngine } from "@/lib/engine";

describe("internal user resolution", () => {
  const callbackUser = {
    id: "adapter-user-1",
    email: "player@example.com",
    emailVerified: null,
  } as AdapterUser;

  it("builds normalized google identity profile from validated claims", () => {
    const identity = buildGoogleIdentityProfile({
      account: { provider: "google", providerAccountId: "provider-account-sub" },
      profile: {
        sub: "google-oidc-subject",
        iss: "accounts.google.com",
        email: "player@example.com",
        email_verified: true,
        name: "Player Name",
        picture: "https://example.com/p.png",
      },
    });

    expect(identity.providerIssuer).toBe(CANONICAL_GOOGLE_ISSUER);
    expect(identity.providerSubject).toBe("google-oidc-subject");
    expect(identity.email).toBe("player@example.com");
  });

  it("uses the centralized fetchEngine client and sends only normalized identity fields", async () => {
    vi.mocked(fetchEngine).mockResolvedValue(
      new Response(JSON.stringify({ user_id: "user_abc" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const userId = await resolveInternalUserId({
      identityProvider: "google",
      providerIssuer: CANONICAL_GOOGLE_ISSUER,
      providerSubject: "google-subject",
      email: "player@example.com",
      emailVerified: true,
      displayName: "Player",
      avatarUrl: "https://example.com/avatar.png",
    });

    expect(userId).toBe("user_abc");
    expect(fetchEngine).toHaveBeenCalledTimes(1);
    const [, init] = vi.mocked(fetchEngine).mock.calls[0];
    const body = JSON.parse(String(init?.body));

    expect(body).toEqual({
      identity_provider: "google",
      provider_issuer: CANONICAL_GOOGLE_ISSUER,
      provider_subject: "google-subject",
      email: "player@example.com",
      email_verified: true,
      display_name: "Player",
      avatar_url: "https://example.com/avatar.png",
    });

    expect(Object.keys(body)).not.toContain("access_token");
    expect(Object.keys(body)).not.toContain("refresh_token");
    expect(Object.keys(body)).not.toContain("id_token");
    expect(Object.keys(body)).not.toContain("profile");
  });

  it("resolves once on initial google login and reuses user id on later jwt reads", async () => {
    vi.mocked(fetchEngine).mockResolvedValue(
      new Response(JSON.stringify({ user_id: "user_once" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const jwt = authOptions.callbacks?.jwt;
    if (!jwt) {
      throw new Error("jwt callback is not configured");
    }

    const first = await jwt({
      token: {},
      account: { provider: "google", providerAccountId: "subject-123" } as never,
      profile: {
        sub: "subject-123",
        iss: CANONICAL_GOOGLE_ISSUER,
        email: "player@example.com",
        email_verified: true,
        name: "Player",
      } as never,
      user: callbackUser,
      trigger: "signIn",
      isNewUser: false,
      session: undefined,
    });

    expect(first.internalUserId).toBe("user_once");
    expect(fetchEngine).toHaveBeenCalledTimes(1);

    const second = await jwt({
      token: first,
      account: null,
      profile: undefined,
      user: callbackUser,
      trigger: "update",
      isNewUser: false,
      session: undefined,
    });

    expect(second.internalUserId).toBe("user_once");
    expect(fetchEngine).toHaveBeenCalledTimes(1);
  });

  it("fails closed when internal resolution fails during sign-in", async () => {
    vi.mocked(fetchEngine).mockResolvedValue(new Response("down", { status: 503 }));

    const jwt = authOptions.callbacks?.jwt;
    if (!jwt) {
      throw new Error("jwt callback is not configured");
    }

    await expect(
      jwt({
        token: {},
        account: { provider: "google", providerAccountId: "subject-123" } as never,
        profile: {
          sub: "subject-123",
          iss: CANONICAL_GOOGLE_ISSUER,
          email: "player@example.com",
          email_verified: true,
        } as never,
        user: callbackUser,
        trigger: "signIn",
        isNewUser: false,
        session: undefined,
      })
    ).rejects.toThrow("AccessDenied");
  });

  it("copies the resolved internal user id into the Auth.js session", async () => {
    const sessionCb = authOptions.callbacks?.session;
    if (!sessionCb) {
      throw new Error("session callback is not configured");
    }

    const session = await sessionCb({
      session: {
        user: { name: "Player", email: "player@example.com", image: null },
        expires: "2099-01-01T00:00:00.000Z",
      } as never,
      token: { internalUserId: "user_xyz" } as never,
      user: callbackUser,
      newSession: {},
      trigger: "update",
    } as never);

    expect((session as { internalUserId?: string }).internalUserId).toBe("user_xyz");
  });
});
