import { NextResponse } from "next/server";
import {
  fetchEngine,
  isInternalEngineRequestError,
  respondWithEngineError,
  respondWithInternalEngineError,
  getTemporaryPlayerId,
} from "@/lib/engine";
import { ensureAuthenticated } from "@/lib/route-auth";

function isValidPlayerId(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.trim().toLowerCase() !== "anonymous";
}

export async function GET(request: Request, { params }: { params: Promise<{ character_id: string }> }) {
  try {
    const { response: authResponse } = await ensureAuthenticated();
    if (authResponse) {
      return authResponse;
    }

    const { character_id } = await params;
    const playerId = new URL(request.url).searchParams.get("player_id")?.trim() || getTemporaryPlayerId();

    if (!character_id?.trim()) {
      return NextResponse.json({ error: "character_id is required" }, { status: 400 });
    }

    if (!isValidPlayerId(playerId)) {
      return NextResponse.json(
        { error: "A valid player_id query parameter is required" },
        { status: 422 }
      );
    }

    const response = await fetchEngine(
      `/api/character/${encodeURIComponent(character_id)}?player_id=${encodeURIComponent(playerId)}`
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

    return NextResponse.json(
      { error: "Unable to proxy character request", details: (error as Error).message },
      { status: 500 }
    );
  }
}
