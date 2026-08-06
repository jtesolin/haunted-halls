import { NextResponse } from "next/server";
import {
  fetchEngineAsUser,
  isInternalEngineRequestError,
  respondWithEngineError,
  respondWithInternalEngineError,
  getTemporaryPlayerId,
} from "@/lib/engine";
import { ensureAuthenticated } from "@/lib/route-auth";

function isValidPlayerId(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.trim().toLowerCase() !== "anonymous";
}

export async function GET(_request: Request, { params }: { params: Promise<{ player_id: string }> }) {
  try {
    const { response: authResponse, internalUserId } = await ensureAuthenticated();
    if (authResponse) {
      return authResponse;
    }

    if (!internalUserId) {
      console.error("characters list proxy: missing internal user context after authentication");
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }

    await params;
    const player_id = getTemporaryPlayerId();

    if (!isValidPlayerId(player_id)) {
      return NextResponse.json(
        { error: "A valid player_id is required" },
        { status: 422 }
      );
    }

    const response = await fetchEngineAsUser(
      `/api/characters/${encodeURIComponent(player_id)}`,
      internalUserId
    );

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

    return NextResponse.json(
      { error: "Unable to proxy characters request", details: (error as Error).message },
      { status: 500 }
    );
  }
}
