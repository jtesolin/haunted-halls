/* @vitest-environment node */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}));

import { getServerSession } from "next-auth";
import { GET as getExploration } from "@/app/api/campaign/[campaign_id]/exploration/route";
import { GET as getRoom } from "@/app/api/campaign/[campaign_id]/exploration/rooms/[room_id]/route";
import { INTERNAL_ENGINE_USER_ID_HEADER } from "@/lib/engine";

const TOKEN = "test-internal-engine-service-token-0000000000000000000000000000000000";
const USER_ID = "user_0123456789abcdef0123456789abcdef";
const originalToken = process.env.INTERNAL_ENGINE_SERVICE_TOKEN;

const request = new Request("http://localhost:3000/api/campaign/c1/exploration");

describe("exploration BFF routes", () => {
  beforeEach(() => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    vi.mocked(getServerSession).mockReset();
    process.env.INTERNAL_ENGINE_SERVICE_TOKEN = TOKEN;
  });

  afterEach(() => {
    if (originalToken === undefined) {
      delete process.env.INTERNAL_ENGINE_SERVICE_TOKEN;
    } else {
      process.env.INTERNAL_ENGINE_SERVICE_TOKEN = originalToken;
    }
  });

  it("rejects unauthenticated requests without calling the engine", async () => {
    vi.mocked(getServerSession).mockResolvedValue(null);

    const graph = await getExploration(request, { params: Promise.resolve({ campaign_id: "c1" }) });
    const room = await getRoom(request, { params: Promise.resolve({ campaign_id: "c1", room_id: "hall" }) });

    expect(graph.status).toBe(401);
    expect(room.status).toBe(401);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("proxies the graph with the trusted internal user header", async () => {
    vi.mocked(getServerSession).mockResolvedValue({ internalUserId: USER_ID } as never);
    const payload = { current_location: { id: "hall", name: "Hall" }, nodes: [], edges: [], observations: [] };
    vi.mocked(global.fetch).mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }));

    const response = await getExploration(request, { params: Promise.resolve({ campaign_id: "c 1" }) });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(payload);
    const [url, init] = vi.mocked(global.fetch).mock.calls[0];
    expect(String(url)).toMatch(/\/api\/campaign\/c%201\/exploration$/);
    expect(new Headers(init?.headers).get(INTERNAL_ENGINE_USER_ID_HEADER)).toBe(USER_ID);
  });

  it("proxies room notes with both path segments encoded", async () => {
    vi.mocked(getServerSession).mockResolvedValue({ internalUserId: USER_ID } as never);
    vi.mocked(global.fetch).mockResolvedValue(
      new Response(JSON.stringify({ room: { id: "a/b", name: "A" }, current: false, notes: ["n"] }), { status: 200 })
    );

    const response = await getRoom(request, { params: Promise.resolve({ campaign_id: "c1", room_id: "a/b" }) });

    expect(response.status).toBe(200);
    const [url] = vi.mocked(global.fetch).mock.calls[0];
    expect(String(url)).toMatch(/\/api\/campaign\/c1\/exploration\/rooms\/a%2Fb$/);
  });

  it("maps an engine 404 for an undiscovered room to a public 404", async () => {
    vi.mocked(getServerSession).mockResolvedValue({ internalUserId: USER_ID } as never);
    vi.mocked(global.fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: "Room not found" }), { status: 404 })
    );

    const response = await getRoom(request, { params: Promise.resolve({ campaign_id: "c1", room_id: "secret" }) });

    expect(response.status).toBe(404);
  });

  it("rejects blank ids before calling the engine", async () => {
    vi.mocked(getServerSession).mockResolvedValue({ internalUserId: USER_ID } as never);

    const response = await getRoom(request, { params: Promise.resolve({ campaign_id: "c1", room_id: " " }) });

    expect(response.status).toBe(400);
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
