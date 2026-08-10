import { NextResponse } from "next/server";
import {
  fetchEngineAsUser,
  isInternalEngineRequestError,
  respondWithEngineError,
  respondWithInternalEngineError,
  respondWithUnexpectedProxyError,
} from "@/lib/engine";
import { ensureAuthenticated } from "@/lib/route-auth";

export async function GET(_request: Request, { params }: { params: Promise<{ character_id: string }> }) {
  try {
    const { response: authResponse, internalUserId } = await ensureAuthenticated();
    if (authResponse) {
      return authResponse;
    }

    if (!internalUserId) {
      console.error("character read proxy: missing internal user context after authentication");
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }

    const { character_id } = await params;

    if (!character_id?.trim()) {
      return NextResponse.json({ error: "character_id is required" }, { status: 400 });
    }

    const response = await fetchEngineAsUser(
      `/api/character/${encodeURIComponent(character_id)}`,
      internalUserId
    );

    if (!response.ok) {
      return await respondWithEngineError(
        response,
        "character read proxy",
        "Backend service unavailable"
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    if (isInternalEngineRequestError(error)) {
      return respondWithInternalEngineError("character read proxy", error);
    }

    return respondWithUnexpectedProxyError("character read proxy");
  }
}
