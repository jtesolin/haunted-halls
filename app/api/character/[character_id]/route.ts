import { NextResponse } from "next/server";

export async function GET(_request: Request, { params }: { params: Promise<{ character_id: string }> }) {
  try {
    const { character_id } = await params;

    if (!character_id?.trim()) {
      return NextResponse.json({ error: "character_id is required" }, { status: 400 });
    }

    const response = await fetch(`http://localhost:8000/api/character/${encodeURIComponent(character_id)}`);

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
      { error: "Unable to proxy character request", details: (error as Error).message },
      { status: 500 }
    );
  }
}
