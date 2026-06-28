import { NextResponse } from "next/server";

export async function GET(_request: Request, { params }: { params: Promise<{ campaign_id: string }> }) {
  try {
    const { campaign_id } = await params;

    if (!campaign_id?.trim()) {
      return NextResponse.json({ error: "campaign_id is required" }, { status: 400 });
    }

    const response = await fetch(`http://localhost:8000/api/campaign/${encodeURIComponent(campaign_id)}`);

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
      { error: "Unable to proxy campaign request", details: (error as Error).message },
      { status: 500 }
    );
  }
}
