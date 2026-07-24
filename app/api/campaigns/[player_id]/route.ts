import { NextResponse } from "next/server";
import { getEngineAuthHeaders, getEngineBaseUrl, getTemporaryPlayerId } from "@/lib/engine";
import { ensureAuthenticated } from "@/lib/route-auth";

function isValidPlayerId(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.trim().toLowerCase() !== "anonymous";
}

export async function GET(_request: Request, { params }: { params: Promise<{ player_id: string }> }) {
  try {
    const { response: authResponse } = await ensureAuthenticated();
    if (authResponse) {
      return authResponse;
    }

    await params;
    const player_id = getTemporaryPlayerId();

    if (!isValidPlayerId(player_id)) {
      return NextResponse.json(
        { error: "A valid player_id is required" },
        { status: 422 }
      );
    }

    const response = await fetch(`${getEngineBaseUrl()}/api/campaigns/${encodeURIComponent(player_id)}`, {
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
      { error: "Unable to proxy campaigns request", details: (error as Error).message },
      { status: 500 }
    );
  }
}
