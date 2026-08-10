import { NextResponse } from "next/server";
import type { CreateCampaignRequest, CreateCampaignResponse } from "@/types/chat";
import {
  fetchEngineAsUser,
  isInternalEngineRequestError,
  respondWithEngineError,
  respondWithInternalEngineError,
  respondWithUnexpectedProxyError,
} from "@/lib/engine";
import { ensureAllowedMutationOrigin, ensureAuthenticated } from "@/lib/route-auth";

export async function POST(request: Request) {
  try {
    const { response: authResponse, internalUserId } = await ensureAuthenticated();
    if (authResponse) {
      return authResponse;
    }

    const originResponse = ensureAllowedMutationOrigin(request, "campaign create proxy");
    if (originResponse) {
      return originResponse;
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

    return respondWithUnexpectedProxyError("campaign create proxy");
  }
}