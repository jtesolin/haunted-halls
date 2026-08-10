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

function forbiddenResponse() {
  return NextResponse.json({ error: "Forbidden" }, { status: 403 });
}

function getAllowedAppOrigin(request: Request) {
  const configuredOrigin = process.env.NEXTAUTH_URL?.trim();

  if (configuredOrigin) {
    try {
      return new URL(configuredOrigin).origin;
    } catch {
      console.error("configured NEXTAUTH_URL is not a valid origin");
    }
  }

  return new URL(request.url).origin;
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

export function ensureAllowedMutationOrigin(request: Request, context: string) {
  const originHeader = request.headers.get("origin");

  if (!originHeader) {
    return null;
  }

  let requestOrigin = "";

  try {
    requestOrigin = new URL(originHeader).origin;
  } catch {
    console.warn(`${context}: rejected mutation request with invalid Origin header`);
    return forbiddenResponse();
  }

  const allowedOrigin = getAllowedAppOrigin(request);
  if (requestOrigin !== allowedOrigin) {
    console.warn(`${context}: rejected cross-origin mutation request`, {
      origin: requestOrigin,
    });
    return forbiddenResponse();
  }

  return null;
}
