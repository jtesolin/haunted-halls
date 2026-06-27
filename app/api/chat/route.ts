import { NextResponse } from "next/server";
import type { ChatRequest, ChatResponse } from "@/types/chat";

export async function POST(request: Request) {
  try {
    const body: ChatRequest = await request.json();
    const payload: ChatRequest = {
      message: body.message,
      campaign_id: body.campaign_id,
      character_id: body.character_id,
    };

    const response = await fetch("http://localhost:8000/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
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

    const data: ChatResponse = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { error: "Unable to proxy chat request", details: (error as Error).message },
      { status: 500 }
    );
  }
}
