import type { NextAuthOptions } from "next-auth";
import GoogleProvider from "next-auth/providers/google";
import CredentialsProvider from "next-auth/providers/credentials";
import {
  buildGoogleIdentityProfile,
  InternalUserResolutionError,
  resolveInternalUserId,
} from "@/lib/internal-user-resolution";
import { E2E_FIXED_IDENTITY, E2E_PROVIDER_ID, isE2EAuthEnabled } from "@/lib/e2e-auth";
import { getAuthMode } from "@/lib/auth-mode";
import { getIapExpectedAudience, IAP_PROVIDER_ID, verifyIapIdentity } from "@/lib/iap-auth";

function getRequiredEnv(name: string): string {
  const value = process.env[name]?.trim();

  if (!value && process.env.NODE_ENV !== "test") {
    throw new Error(`${name} is required for authentication`);
  }

  return value || `test-${name.toLowerCase()}`;
}

function isE2ESessionAllowed(): boolean {
  try {
    return getAuthMode() === "e2e" && isE2EAuthEnabled();
  } catch {
    return false;
  }
}

const mode = getAuthMode();
const providers: NextAuthOptions["providers"] = [];

if (mode === "google") {
  providers.push(
    GoogleProvider({
      clientId: getRequiredEnv("GOOGLE_CLIENT_ID"),
      clientSecret: getRequiredEnv("GOOGLE_CLIENT_SECRET"),
      authorization: {
        params: {
          scope: "openid email profile",
        },
      },
    })
  );
}

if (mode === "iap") {
  const audience = getIapExpectedAudience();
  providers.push(
    CredentialsProvider({
      id: IAP_PROVIDER_ID,
      name: "IAP",
      credentials: {},
      async authorize(_credentials, request) {
        try {
          const identity = await verifyIapIdentity(
            request.headers?.["x-goog-iap-jwt-assertion"],
            audience
          );
          const internalUserId = await resolveInternalUserId(identity);
          return {
            id: identity.providerSubject,
            email: identity.email,
            internalUserId,
          };
        } catch {
          console.error("iap auth sign-in failed during verification or internal user resolution");
          throw new Error("AccessDenied");
        }
      },
    })
  );
}

// Guarded, loopback-only, test-only authentication seam. See lib/e2e-auth.ts for the
// safety boundary. This never accepts browser-supplied identity fields; it always
// resolves the same fixed synthetic identity through the real engine user-resolution
// path used by the Google provider.
if (mode === "e2e") {
  if (!isE2EAuthEnabled()) {
    throw new Error("AUTH_MODE=e2e requires the guarded E2E_AUTH_ENABLED seam");
  }
  providers.push(
    CredentialsProvider({
      id: E2E_PROVIDER_ID,
      name: "Playwright E2E (test-only)",
      credentials: {},
      async authorize() {
        return {
          id: E2E_FIXED_IDENTITY.providerSubject,
          name: E2E_FIXED_IDENTITY.displayName,
          email: E2E_FIXED_IDENTITY.email,
        };
      },
    })
  );
}

export const authOptions: NextAuthOptions = {
  providers,
  session: {
    strategy: "jwt",
  },
  secret: getRequiredEnv("NEXTAUTH_SECRET"),
  pages: {
    signIn: "/",
    error: "/",
  },
  callbacks: {
    async jwt({ token, account, profile, user }) {
      const currentMode = getAuthMode();
      if (token.authMode !== undefined && token.authMode !== currentMode) {
        throw new Error("AccessDenied");
      }
      if (token.e2eAuth || token.authMode === "e2e") {
        if (!token.e2eAuth || token.authMode !== "e2e" || !isE2ESessionAllowed()) {
          throw new Error("AccessDenied");
        }
      }

      if (token.internalUserId) {
        if (token.authMode === undefined) {
          if (currentMode !== "google") {
            throw new Error("AccessDenied");
          }
          token.authMode = "google";
        }
        return token;
      }

      if (account && account.provider !== currentMode) {
        throw new Error("AccessDenied");
      }

      if (account?.provider === IAP_PROVIDER_ID) {
        if (!user?.internalUserId) {
          throw new Error("AccessDenied");
        }
        token.internalUserId = user.internalUserId;
        token.authMode = "iap";
        return token;
      }

      if (account?.provider === E2E_PROVIDER_ID) {
        if (!isE2ESessionAllowed()) {
          // Defense in depth: even if a stale/misissued e2e JWT is presented, refuse
          // to trust it unless the guard is currently satisfied for this process.
          throw new Error("AccessDenied");
        }

        try {
          token.internalUserId = await resolveInternalUserId(E2E_FIXED_IDENTITY);
          token.e2eAuth = true;
          token.authMode = "e2e";
        } catch (error) {
          if (error instanceof InternalUserResolutionError) {
            console.error("e2e auth sign-in failed during internal user resolution");
          } else {
            console.error("e2e auth sign-in failed due to internal resolution dependency");
          }
          throw new Error("AccessDenied");
        }

        return token;
      }

      if (account?.provider !== "google" || !profile) {
        return token;
      }

      try {
        const identity = buildGoogleIdentityProfile({
          account,
          profile: profile as Record<string, unknown>,
        });
        token.internalUserId = await resolveInternalUserId(identity);
        token.authMode = "google";
      } catch (error) {
        if (error instanceof InternalUserResolutionError) {
          console.error("auth sign-in failed during internal user resolution", {
            provider: account.provider,
            subject_hint:
              typeof (profile as Record<string, unknown>).sub === "string"
                ? (profile as Record<string, unknown>).sub
                : account.providerAccountId,
          });
        } else {
          console.error("auth sign-in failed due to internal resolution dependency");
        }
        throw new Error("AccessDenied");
      }

      return token;
    },
    async session({ session, token }) {
      return {
        ...session,
        internalUserId: typeof token.internalUserId === "string" ? token.internalUserId : undefined,
        user: {
          name: session.user?.name ?? null,
          email: session.user?.email ?? null,
          image: session.user?.image ?? null,
        },
      };
    },
    async redirect({ url, baseUrl }) {
      try {
        const target = new URL(url, baseUrl);
        return target.origin === baseUrl ? target.toString() : baseUrl;
      } catch {
        return baseUrl;
      }
    },
  },
};
