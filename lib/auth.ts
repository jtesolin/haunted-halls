import type { NextAuthOptions } from "next-auth";
import GoogleProvider from "next-auth/providers/google";
import CredentialsProvider from "next-auth/providers/credentials";
import {
  buildGoogleIdentityProfile,
  InternalUserResolutionError,
  resolveInternalUserId,
} from "@/lib/internal-user-resolution";
import { E2E_FIXED_IDENTITY, E2E_PROVIDER_ID, isE2EAuthEnabled } from "@/lib/e2e-auth";

function getRequiredEnv(name: string): string {
  const value = process.env[name]?.trim();

  if (!value && process.env.NODE_ENV !== "test") {
    throw new Error(`${name} is required for authentication`);
  }

  return value || `test-${name.toLowerCase()}`;
}

function isE2ESessionAllowed(): boolean {
  try {
    return isE2EAuthEnabled();
  } catch {
    return false;
  }
}

const providers: NextAuthOptions["providers"] = [
  GoogleProvider({
    clientId: getRequiredEnv("GOOGLE_CLIENT_ID"),
    clientSecret: getRequiredEnv("GOOGLE_CLIENT_SECRET"),
    authorization: {
      params: {
        scope: "openid email profile",
      },
    },
  }),
];

// Guarded, loopback-only, test-only authentication seam. See lib/e2e-auth.ts for the
// safety boundary. This never accepts browser-supplied identity fields; it always
// resolves the same fixed synthetic identity through the real engine user-resolution
// path used by the Google provider.
if (isE2EAuthEnabled()) {
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
    async jwt({ token, account, profile }) {
      if (token.e2eAuth) {
        if (!isE2ESessionAllowed()) {
          throw new Error("AccessDenied");
        }

        return token;
      }

      if (token.internalUserId) {
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
