import type { NextAuthOptions } from "next-auth";
import GoogleProvider from "next-auth/providers/google";

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
    async session({ session }) {
      return {
        ...session,
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
