import { NextResponse } from "next/server";
import {
  fetchEngineAsUser,
  isInternalEngineRequestError,
  respondWithEngineError,
  respondWithInternalEngineError,
} from "@/lib/engine";
import { ensureAuthenticated } from "@/lib/route-auth";

export async function GET() {
  try {
    const { response: authResponse, internalUserId } = await ensureAuthenticated();
    if (authResponse) {
      return authResponse;
    }

    if (!internalUserId) {
      console.error("campaigns list proxy: missing internal user context after authentication");
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }

    const response = await fetchEngineAsUser("/api/campaigns", internalUserId);

    if (!response.ok) {
      return await respondWithEngineError(
        response,
        "campaigns list proxy",
        "Backend service unavailable"
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    if (isInternalEngineRequestError(error)) {
      return respondWithInternalEngineError("campaigns list proxy", error);
    }

    return NextResponse.json(
      { error: "Unable to proxy campaigns request", details: (error as Error).message },
      { status: 500 }
    );
  }
}
