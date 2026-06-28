import { NextResponse } from "next/server";
import type { ChatRequest, ChatResponse } from "@/types/chat";

function isValidPlayerId(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.trim().toLowerCase() !== "anonymous";
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as Partial<ChatRequest>;
    const message = typeof body.message === "string" ? body.message : "";
    const playerId = typeof body.player_id === "string" ? body.player_id.trim() : "";

    if (!message.trim()) {
      return NextResponse.json({ error: "Message is required" }, { status: 400 });
    }

    if (!isValidPlayerId(body.player_id)) {
      return NextResponse.json(
        { error: "A valid player_id is required" },
        { status: 422 }
      );
    }

    const payload: ChatRequest = {
      message,
      campaign_id: typeof body.campaign_id === "string" ? body.campaign_id : null,
      character_id: typeof body.character_id === "string" ? body.character_id : null,
      player_id: playerId,
    };

    const response = await fetch("http://localhost:8000/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const text = await response.text();
      return NextResponse.json(
        { error: "Backend request failed", details: text },
        { status: response.status }
      );
    }

    const data: ChatResponse = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { error: "Unable to proxy chat request", details: (error as Error).message },
      { status: 500 }
    );
  }
}
