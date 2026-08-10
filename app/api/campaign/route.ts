import { NextResponse } from "next/server";
import type { CreateCampaignRequest, CreateCampaignResponse } from "@/types/chat";
import {
  fetchEngineAsUser,
  isInternalEngineRequestError,
  respondWithEngineError,
  respondWithInternalEngineError,
} from "@/lib/engine";
import { ensureAuthenticated } from "@/lib/route-auth";

export async function POST() {
  try {
    const { response: authResponse, internalUserId } = await ensureAuthenticated();
    if (authResponse) {
      return authResponse;
    }

    if (!internalUserId) {
      console.error("campaign create proxy: missing internal user context after authentication");
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }

    const payload: CreateCampaignRequest = {};

    const response = await fetchEngineAsUser("/api/campaign", internalUserId, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      return await respondWithEngineError(
        response,
        "campaign create proxy",
        "Backend service unavailable"
      );
    }

    const data: CreateCampaignResponse = await response.json();
    return NextResponse.json(data, { status: 201 });
  } catch (error) {
    if (isInternalEngineRequestError(error)) {
      return respondWithInternalEngineError("campaign create proxy", error);
    }

    return NextResponse.json(
      { error: "Unable to proxy create campaign request", details: (error as Error).message },
      { status: 500 }
    );
  }
}