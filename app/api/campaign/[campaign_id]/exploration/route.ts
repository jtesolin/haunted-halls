import { NextResponse } from "next/server";
import {
  fetchEngineAsUser,
  isInternalEngineRequestError,
  respondWithEngineError,
  respondWithInternalEngineError,
  readEngineJson,
  respondWithUnexpectedProxyError,
} from "@/lib/engine";
import { ensureAuthenticated } from "@/lib/route-auth";

export async function GET(_request: Request, { params }: { params: Promise<{ campaign_id: string }> }) {
  try {
    const { response: authResponse, internalUserId } = await ensureAuthenticated();
    if (authResponse) {
      return authResponse;
    }

    if (!internalUserId) {
      console.error("exploration read proxy: missing internal user context after authentication");
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }

    const { campaign_id } = await params;

    if (!campaign_id?.trim()) {
      return NextResponse.json({ error: "campaign_id is required" }, { status: 400 });
    }

    const response = await fetchEngineAsUser(
      `/api/campaign/${encodeURIComponent(campaign_id)}/exploration`,
      internalUserId
    );

    if (!response.ok) {
      return await respondWithEngineError(response, "exploration read proxy", "Backend service unavailable");
    }

    const data = await readEngineJson(response);
    return NextResponse.json(data);
  } catch (error) {
    if (isInternalEngineRequestError(error)) {
      return respondWithInternalEngineError("exploration read proxy", error);
    }

    return respondWithUnexpectedProxyError("exploration read proxy");
  }
}
