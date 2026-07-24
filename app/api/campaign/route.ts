import { NextResponse } from "next/server";
import type { CreateCampaignRequest, CreateCampaignResponse } from "@/types/chat";
import { getEngineAuthHeaders, getEngineBaseUrl, getTemporaryPlayerId } from "@/lib/engine";
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

    const body = (await request.json()) as Partial<CreateCampaignRequest>;
    const fallbackPlayerId = getTemporaryPlayerId();
    const providedPlayerId = typeof body.player_id === "string" ? body.player_id.trim() : "";
    const resolvedPlayerId = providedPlayerId || fallbackPlayerId;

    if (!isValidPlayerId(resolvedPlayerId)) {
      return NextResponse.json(
        { error: "A valid player_id is required" },
        { status: 422 }
      );
    }

    const payload: CreateCampaignRequest = {
      player_id: resolvedPlayerId,
    };

    const response = await fetch(`${getEngineBaseUrl()}/api/campaign`, {
      method: "POST",
      headers: {
        ...getEngineAuthHeaders(true),
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

    const data: CreateCampaignResponse = await response.json();
    return NextResponse.json(data, { status: 201 });
  } catch (error) {
    return NextResponse.json(
      { error: "Unable to proxy create campaign request", details: (error as Error).message },
      { status: 500 }
    );
  }
}