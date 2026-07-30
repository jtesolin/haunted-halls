import type { DefaultSession } from "next-auth";

declare module "next-auth" {
  interface Session {
    internalUserId?: string;
    user: {
      name: string | null;
      email: string | null;
      image: string | null;
    } & DefaultSession["user"];
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    internalUserId?: string;
  }
}
