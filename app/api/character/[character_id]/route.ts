import { NextResponse } from "next/server";
import { getEngineAuthHeaders, getEngineBaseUrl } from "@/lib/engine";

function isValidPlayerId(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.trim().toLowerCase() !== "anonymous";
}

export async function GET(request: Request, { params }: { params: Promise<{ character_id: string }> }) {
  try {
    const { character_id } = await params;
    const playerId = new URL(request.url).searchParams.get("player_id")?.trim() ?? "";

    if (!character_id?.trim()) {
      return NextResponse.json({ error: "character_id is required" }, { status: 400 });
    }

    if (!isValidPlayerId(playerId)) {
      return NextResponse.json(
        { error: "A valid player_id query parameter is required" },
        { status: 422 }
      );
    }

    const url = new URL(`${getEngineBaseUrl()}/api/character/${encodeURIComponent(character_id)}`);
    url.searchParams.set("player_id", playerId);

    const response = await fetch(url, {
      headers: {
        ...getEngineAuthHeaders(),
      },
    });

    if (!response.ok) {
      const text = await response.text();
      return NextResponse.json(
        { error: "Backend request failed", details: text },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { error: "Unable to proxy character request", details: (error as Error).message },
      { status: 500 }
    );
  }
}
