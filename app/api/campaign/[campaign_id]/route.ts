import { NextResponse } from "next/server";
import {
  fetchEngineAsUser,
  isInternalEngineRequestError,
  respondWithEngineError,
  respondWithInternalEngineError,
  respondWithUnexpectedProxyError,
} from "@/lib/engine";
import { ensureAllowedMutationOrigin, ensureAuthenticated } from "@/lib/route-auth";

export async function GET(_request: Request, { params }: { params: Promise<{ campaign_id: string }> }) {
  try {
    const { response: authResponse, internalUserId } = await ensureAuthenticated();
    if (authResponse) {
      return authResponse;
    }

    if (!internalUserId) {
      console.error("campaign read proxy: missing internal user context after authentication");
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }

    const { campaign_id } = await params;

    if (!campaign_id?.trim()) {
      return NextResponse.json({ error: "campaign_id is required" }, { status: 400 });
    }

    const response = await fetchEngineAsUser(
      `/api/campaign/${encodeURIComponent(campaign_id)}`,
      internalUserId
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

    return respondWithUnexpectedProxyError("campaign read proxy");
  }
}

export async function DELETE(request: Request, { params }: { params: Promise<{ campaign_id: string }> }) {
  try {
    const { response: authResponse, internalUserId } = await ensureAuthenticated();
    if (authResponse) {
      return authResponse;
    }

    const originResponse = ensureAllowedMutationOrigin(request, "campaign delete proxy");
    if (originResponse) {
      return originResponse;
    }

    if (!internalUserId) {
      console.error("campaign delete proxy: missing internal user context after authentication");
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }

    const { campaign_id } = await params;

    if (!campaign_id?.trim()) {
      return NextResponse.json({ error: "campaign_id is required" }, { status: 400 });
    }

    const response = await fetchEngineAsUser(
      `/api/campaign/${encodeURIComponent(campaign_id)}`,
      internalUserId,
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

    return respondWithUnexpectedProxyError("campaign delete proxy");
  }
}
