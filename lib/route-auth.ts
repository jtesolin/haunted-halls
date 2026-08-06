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

  if (!session) {
    return {
      session: null,
      internalUserId: null,
      response: unauthenticatedResponse(),
    };
  }

  if (typeof session.internalUserId !== "string" || !session.internalUserId.trim()) {
    console.error("authenticated session is missing internal user context");
    return {
      session: null,
      internalUserId: null,
      response: unauthenticatedResponse(),
    };
  }

  return {
    session: session as AuthenticatedSession,
    internalUserId: session.internalUserId.trim(),
    response: null,
  };
}

export async function ensureAuthenticated() {
  const { session, internalUserId, response } = await requireAuthenticatedUser();
  return { session, internalUserId, response };
}
