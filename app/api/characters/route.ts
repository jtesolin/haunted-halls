import { NextResponse } from "next/server";
import {
  fetchEngineAsUser,
  isInternalEngineRequestError,
  respondWithEngineError,
  respondWithInternalEngineError,
  respondWithUnexpectedProxyError,
} from "@/lib/engine";
import { ensureAuthenticated } from "@/lib/route-auth";

export async function GET() {
  try {
    const { response: authResponse, internalUserId } = await ensureAuthenticated();
    if (authResponse) {
      return authResponse;
    }

    if (!internalUserId) {
      console.error("characters list proxy: missing internal user context after authentication");
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }

    const response = await fetchEngineAsUser("/api/characters", internalUserId);

    if (!response.ok) {
      return await respondWithEngineError(
        response,
        "characters list proxy",
        "Backend service unavailable"
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    if (isInternalEngineRequestError(error)) {
      return respondWithInternalEngineError("characters list proxy", error);
    }

    return respondWithUnexpectedProxyError("characters list proxy");
  }
}
