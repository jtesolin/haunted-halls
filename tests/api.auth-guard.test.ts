/* @vitest-environment node */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}));

import { getServerSession } from "next-auth";
import { POST as postChat } from "@/app/api/chat/route";
import { POST as postCampaign } from "@/app/api/campaign/route";
import { GET as getCampaign } from "@/app/api/campaign/[campaign_id]/route";
import { INTERNAL_ENGINE_USER_ID_HEADER } from "@/lib/engine";

const TEST_INTERNAL_ENGINE_SERVICE_TOKEN =
  "test-internal-engine-service-token-0000000000000000000000000000000000";

const originalInternalEngineServiceToken = process.env.INTERNAL_ENGINE_SERVICE_TOKEN;

describe("BFF auth guard", () => {
  beforeEach(() => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    vi.mocked(global.fetch).mockReset();
    vi.mocked(getServerSession).mockReset();
    process.env.INTERNAL_ENGINE_SERVICE_TOKEN = TEST_INTERNAL_ENGINE_SERVICE_TOKEN;
  });

  afterEach(() => {
    if (originalInternalEngineServiceToken === undefined) {
      delete process.env.INTERNAL_ENGINE_SERVICE_TOKEN;
    } else {
      process.env.INTERNAL_ENGINE_SERVICE_TOKEN = originalInternalEngineServiceToken;
    }
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

  it("adds the internal bearer token for authenticated chat requests and strips browser authorization", async () => {
    vi.mocked(getServerSession).mockResolvedValue({ internalUserId: "user_0123456789abcdef0123456789abcdef" } as never);
    vi.mocked(global.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          reply: "ok",
          campaign_id: "campaign-1",
          turn_id: "turn-1",
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      )
    );

    const request = new Request("http://localhost:3000/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer browser-token",
        [INTERNAL_ENGINE_USER_ID_HEADER]: "user_browser_supplied",
      },
      body: JSON.stringify({ message: "look", player_id: "player-1", internal_user_id: "user_body_supplied" }),
    });

    const response = await postChat(request);

    expect(response.status).toBe(200);
    expect(global.fetch).toHaveBeenCalledTimes(1);

    const [target, init] = vi.mocked(global.fetch).mock.calls[0];
    expect(String(target)).toContain("/api/chat");

    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe(`Bearer ${TEST_INTERNAL_ENGINE_SERVICE_TOKEN}`);
    expect(headers.get("authorization")).toBe(`Bearer ${TEST_INTERNAL_ENGINE_SERVICE_TOKEN}`);
    expect(headers.get(INTERNAL_ENGINE_USER_ID_HEADER)).toBe(
      "user_0123456789abcdef0123456789abcdef"
    );
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("fails closed when a session exists without an internal user id", async () => {
    vi.mocked(getServerSession).mockResolvedValue(
      {
        user: { name: "Player", email: "player@example.com", image: null },
      } as never
    );

    const request = new Request("http://localhost:3000/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "look", player_id: "player-1" }),
    });

    const response = await postChat(request);
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body.error).toBe("Authentication required");
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("sanitizes internal engine auth failures before they reach the browser", async () => {
    vi.mocked(getServerSession).mockResolvedValue({ internalUserId: "user_0123456789abcdef0123456789abcdef" } as never);
    vi.mocked(global.fetch).mockResolvedValue(
      new Response("missing service credential", {
        status: 401,
        headers: { "Content-Type": "text/plain" },
      })
    );

    const request = new Request("http://localhost:3000/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "look", player_id: "player-1" }),
    });

    const response = await postChat(request);
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body.error).toBe("Backend service unavailable");
    expect(JSON.stringify(body)).not.toContain("missing service credential");
    expect(JSON.stringify(body)).not.toContain(TEST_INTERNAL_ENGINE_SERVICE_TOKEN);
  });

  it("uses trusted session identity for campaign requests and ignores query/body identity hints", async () => {
    vi.mocked(getServerSession).mockResolvedValue({ internalUserId: "user_0123456789abcdef0123456789abcdef" } as never);
    vi.mocked(global.fetch).mockResolvedValue(
      new Response(JSON.stringify({ campaign_id: "campaign-1", player_id: "player-1", name: "X", messages: [], truncated: false }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const request = new Request(
      "http://localhost:3000/api/campaign/campaign-1?player_id=player-1&internal_user_id=user_query_supplied",
      {
        method: "GET",
        headers: {
          Authorization: "Bearer browser-token",
          [INTERNAL_ENGINE_USER_ID_HEADER]: "user_header_supplied",
        },
      }
    );

    const response = await getCampaign(request, { params: Promise.resolve({ campaign_id: "campaign-1" }) });

    expect(response.status).toBe(200);
    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [, init] = vi.mocked(global.fetch).mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(headers.get(INTERNAL_ENGINE_USER_ID_HEADER)).toBe("user_0123456789abcdef0123456789abcdef");
  });
});
