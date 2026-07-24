/* @vitest-environment node */

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}));

import { getServerSession } from "next-auth";
import { POST as postChat } from "@/app/api/chat/route";
import { POST as postCampaign } from "@/app/api/campaign/route";

describe("BFF auth guard", () => {
  beforeEach(() => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    vi.mocked(global.fetch).mockReset();
    vi.mocked(getServerSession).mockReset();
  });

  it("returns 401 and skips FastAPI for unauthenticated chat", async () => {
    vi.mocked(getServerSession).mockResolvedValue(null);

    const request = new Request("http://localhost:3000/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "look" }),
    });

    const response = await postChat(request);
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body.error).toBe("Authentication required");
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("returns 401 and skips FastAPI for unauthenticated campaign creation", async () => {
    vi.mocked(getServerSession).mockResolvedValue(null);

    const request = new Request("http://localhost:3000/api/campaign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });

    const response = await postCampaign(request);
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body.error).toBe("Authentication required");
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
