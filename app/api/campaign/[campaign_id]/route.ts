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

export async function GET(request: Request, { params }: { params: Promise<{ campaign_id: string }> }) {
  try {
    const { response: authResponse } = await ensureAuthenticated();
    if (authResponse) {
      return authResponse;
    }

    const { campaign_id } = await params;
    const playerId = new URL(request.url).searchParams.get("player_id")?.trim() || getTemporaryPlayerId();

    if (!campaign_id?.trim()) {
      return NextResponse.json({ error: "campaign_id is required" }, { status: 400 });
    }

    if (!isValidPlayerId(playerId)) {
      return NextResponse.json(
        { error: "A valid player_id query parameter is required" },
        { status: 422 }
      );
    }

    const response = await fetchEngine(
      `/api/campaign/${encodeURIComponent(campaign_id)}?player_id=${encodeURIComponent(playerId)}`
    );

    if (!response.ok) {
      return await respondWithEngineError(
        response,
        "campaign read proxy",
        "Backend service unavailable"
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    if (isInternalEngineRequestError(error)) {
      return respondWithInternalEngineError("campaign read proxy", error);
    }

    return NextResponse.json(
      { error: "Unable to proxy campaign request", details: (error as Error).message },
      { status: 500 }
    );
  }
}

export async function DELETE(request: Request, { params }: { params: Promise<{ campaign_id: string }> }) {
  try {
    const { response: authResponse } = await ensureAuthenticated();
    if (authResponse) {
      return authResponse;
    }

    const { campaign_id } = await params;
    const playerId = new URL(request.url).searchParams.get("player_id")?.trim() || getTemporaryPlayerId();

    if (!campaign_id?.trim()) {
      return NextResponse.json({ error: "campaign_id is required" }, { status: 400 });
    }

    if (!isValidPlayerId(playerId)) {
      return NextResponse.json(
        { error: "A valid player_id query parameter is required" },
        { status: 422 }
      );
    }

    const response = await fetchEngine(
      `/api/campaign/${encodeURIComponent(campaign_id)}?player_id=${encodeURIComponent(playerId)}`,
      {
        method: "DELETE",
      }
    );

    if (!response.ok) {
      return await respondWithEngineError(
        response,
        "campaign delete proxy",
        "Backend service unavailable"
      );
    }

    return new Response(null, { status: 204 });
  } catch (error) {
    if (isInternalEngineRequestError(error)) {
      return respondWithInternalEngineError("campaign delete proxy", error);
    }

    return NextResponse.json(
      { error: "Unable to proxy delete campaign request", details: (error as Error).message },
      { status: 500 }
    );
  }
}
