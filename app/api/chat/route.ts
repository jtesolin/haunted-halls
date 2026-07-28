import { NextResponse } from "next/server";
import type { ChatRequest, ChatResponse } from "@/types/chat";
import {
  fetchEngine,
  isInternalEngineRequestError,
  respondWithEngineError,
  respondWithInternalEngineError,
  getMaxInputCharacters,
  getTemporaryPlayerId,
} from "@/lib/engine";
import { ensureAuthenticated } from "@/lib/route-auth";

function isValidPlayerId(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.trim().toLowerCase() !== "anonymous";
}

export async function POST(request: Request) {
  try {
    const { response: authResponse } = await ensureAuthenticated();
    if (authResponse) {
      return authResponse;
    }

    const body = (await request.json()) as Partial<ChatRequest>;
    const message = typeof body.message === "string" ? body.message : "";
    const providedPlayerId = typeof body.player_id === "string" ? body.player_id.trim() : "";
    const playerId = providedPlayerId || getTemporaryPlayerId();
    const maxInputCharacters = getMaxInputCharacters();

    if (!message.trim()) {
      return NextResponse.json({ error: "Message is required" }, { status: 400 });
    }

    if (message.length > maxInputCharacters) {
      return NextResponse.json(
        { error: `Message exceeds the ${maxInputCharacters}-character limit` },
        { status: 400 }
      );
    }

    if (!isValidPlayerId(playerId)) {
      return NextResponse.json(
        { error: "A valid player_id is required" },
        { status: 422 }
      );
    }

    const payload: ChatRequest = {
      message,
      campaign_id: typeof body.campaign_id === "string" && body.campaign_id.trim().length > 0 ? body.campaign_id : null,
      character_id: typeof body.character_id === "string" && body.character_id.trim().length > 0 ? body.character_id : null,
      player_id: playerId,
    };

    const response = await fetchEngine("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      return await respondWithEngineError(response, "chat proxy", "Backend service unavailable");
    }

    const data: ChatResponse = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    if (isInternalEngineRequestError(error)) {
      return respondWithInternalEngineError("chat proxy", error);
    }

    return NextResponse.json(
      { error: "Unable to proxy chat request", details: (error as Error).message },
      { status: 500 }
    );
  }
}
