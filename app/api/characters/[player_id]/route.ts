import { NextResponse } from "next/server";

function isValidPlayerId(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.trim().toLowerCase() !== "anonymous";
}

export async function GET(_request: Request, { params }: { params: Promise<{ player_id: string }> }) {
  try {
    const { player_id } = await params;

    if (!isValidPlayerId(player_id)) {
      return NextResponse.json(
        { error: "A valid player_id is required" },
        { status: 422 }
      );
    }

    const response = await fetch(`http://localhost:8000/api/characters/${encodeURIComponent(player_id)}`);

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
      { error: "Unable to proxy characters request", details: (error as Error).message },
      { status: 500 }
    );
  }
}
