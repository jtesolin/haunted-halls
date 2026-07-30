import { getServerSession } from "next-auth";
import { NextResponse } from "next/server";
import { authOptions } from "@/lib/auth";

type AuthenticatedSession = {
  internalUserId: string;
  user: {
    name: string | null;
    email: string | null;
    image: string | null;
  };
};

function unauthenticatedResponse() {
  return NextResponse.json({ error: "Authentication required" }, { status: 401 });
}

export async function requireAuthenticatedUser() {
  const session = await getServerSession(authOptions);

  if (!session || typeof session.internalUserId !== "string" || !session.internalUserId.trim()) {
    return {
      session: null,
      internalUserId: null,
      response: unauthenticatedResponse(),
    };
  }

  return {
    session: session as AuthenticatedSession,
    internalUserId: session.internalUserId,
    response: null,
  };
}

export async function ensureAuthenticated() {
  const { session, response } = await requireAuthenticatedUser();
  return { session, response };
}
