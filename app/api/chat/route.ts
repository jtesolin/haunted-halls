import { NextResponse } from "next/server";
import type { ChatRequest, ChatResponse } from "@/types/chat";
import {
  fetchEngineAsUser,
  isInternalEngineRequestError,
  respondWithEngineError,
  respondWithInternalEngineError,
  respondWithUnexpectedProxyError,
  getMaxInputCharacters,
} from "@/lib/engine";
import { ensureAllowedMutationOrigin, ensureAuthenticated } from "@/lib/route-auth";

export async function POST(request: Request) {
  try {
    const { response: authResponse, internalUserId } = await ensureAuthenticated();
    if (authResponse) {
      return authResponse;
    }

    const originResponse = ensureAllowedMutationOrigin(request, "chat proxy");
    if (originResponse) {
      return originResponse;
    }

    if (!internalUserId) {
      console.error("chat proxy: missing internal user context after authentication");
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }

    const body = (await request.json()) as Record<string, unknown>;
    const message = typeof body.message === "string" ? body.message : "";
    const maxInputCharacters = getMaxInputCharacters();

    if (!message.trim()) {
      return NextResponse.json({ error: "Message is required" }, { status: 400 });
    }

    if (message.length > maxInputCharacters) {
      return NextResponse.json(
        { error: `Message exceeds the ${maxInputCharacters}-character limit` },
        { status: 400 }
      );
    }

    const payload: ChatRequest = {
      message,
      campaign_id: typeof body.campaign_id === "string" && body.campaign_id.trim().length > 0 ? body.campaign_id : null,
      character_id: typeof body.character_id === "string" && body.character_id.trim().length > 0 ? body.character_id : null,
    };

    const response = await fetchEngineAsUser("/api/chat", internalUserId, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      return await respondWithEngineError(response, "chat proxy", "Backend service unavailable");
    }

    const data: ChatResponse = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    if (isInternalEngineRequestError(error)) {
      return respondWithInternalEngineError("chat proxy", error);
    }

    return respondWithUnexpectedProxyError("chat proxy");
  }
}
