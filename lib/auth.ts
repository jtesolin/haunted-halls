import type { NextAuthOptions } from "next-auth";
import GoogleProvider from "next-auth/providers/google";
import {
  buildGoogleIdentityProfile,
  InternalUserResolutionError,
  resolveInternalUserId,
} from "@/lib/internal-user-resolution";

function getRequiredEnv(name: string): string {
  const value = process.env[name]?.trim();

  if (!value && process.env.NODE_ENV !== "test") {
    throw new Error(`${name} is required for authentication`);
  }

  return value || `test-${name.toLowerCase()}`;
}

export const authOptions: NextAuthOptions = {
  providers: [
    GoogleProvider({
      clientId: getRequiredEnv("GOOGLE_CLIENT_ID"),
      clientSecret: getRequiredEnv("GOOGLE_CLIENT_SECRET"),
      authorization: {
        params: {
          scope: "openid email profile",
        },
      },
    }),
  ],
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
      if (token.internalUserId) {
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
