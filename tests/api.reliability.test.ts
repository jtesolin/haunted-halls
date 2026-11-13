/* @vitest-environment node */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}));

import { getServerSession } from "next-auth";
import { POST as postChat } from "@/app/api/chat/route";
import { POST as postCampaign } from "@/app/api/campaign/route";
import { GET as getCampaigns } from "@/app/api/campaigns/route";
import { ENGINE_TIMEOUT_MS, fetchEngineAsUser } from "@/lib/engine";

const TOKEN = "test-internal-engine-service-token-0000000000000000000000000000000000";
const KEY = "123e4567-e89b-42d3-a456-426614174000";
const originalToken = process.env.INTERNAL_ENGINE_SERVICE_TOKEN;

function chatRequest(body: string) {
  return new Request("http://localhost:3000/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": KEY },
    body,
  });
}

describe("chat request validation", () => {
  beforeEach(() => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    vi.mocked(getServerSession).mockReset();
    vi.mocked(getServerSession).mockResolvedValue({
      internalUserId: "user-1",
      user: { name: null, email: null, image: null },
    } as never);
    process.env.INTERNAL_ENGINE_SERVICE_TOKEN = TOKEN;
  });

  afterEach(() => {
    if (originalToken === undefined) delete process.env.INTERNAL_ENGINE_SERVICE_TOKEN;
    else process.env.INTERNAL_ENGINE_SERVICE_TOKEN = originalToken;
  });

  it.each([
    ["malformed JSON", "{not json"],
    ["empty body", ""],
    ["JSON null", "null"],
    ["JSON array", "[]"],
    ["JSON string", '"look"'],
    ["JSON number", "42"],
  ])("returns 400 without contacting the engine for %s", async (_label, body) => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const response = await postChat(chatRequest(body));

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "Request body must be a JSON object" });
    expect(global.fetch).not.toHaveBeenCalled();
    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it("still returns the existing 400 for a JSON object without a message", async () => {
    const response = await postChat(chatRequest("{}"));

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "Message is required" });
    expect(global.fetch).not.toHaveBeenCalled();
  });
});

describe("engine timeout budgets and mapping", () => {
  let timeoutMs: number[];
  let timeoutController: AbortController;

  beforeEach(() => {
    timeoutMs = [];
    timeoutController = new AbortController();
    vi.spyOn(AbortSignal, "timeout").mockImplementation((ms: number) => {
      timeoutMs.push(ms);
      return timeoutController.signal;
    });
    vi.mocked(getServerSession).mockReset();
    vi.mocked(getServerSession).mockResolvedValue({
      internalUserId: "user-1",
      user: { name: null, email: null, image: null },
    } as never);
    process.env.INTERNAL_ENGINE_SERVICE_TOKEN = TOKEN;
    // A fetch that never answers on its own and rejects like undici when its signal aborts.
    global.fetch = vi.fn((_url: unknown, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
      })
    ) as unknown as typeof fetch;
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    if (originalToken === undefined) delete process.env.INTERNAL_ENGINE_SERVICE_TOKEN;
    else process.env.INTERNAL_ENGINE_SERVICE_TOKEN = originalToken;
  });

  // Keep in sync with `timeout = "180s"` on the frontend services in infra/terraform/cloud-run.tf.
  it("keeps every engine budget below the 180s frontend Cloud Run request timeout", () => {
    expect(ENGINE_TIMEOUT_MS.read).toBeLessThan(ENGINE_TIMEOUT_MS.campaignCreate);
    expect(ENGINE_TIMEOUT_MS.campaignCreate).toBeLessThan(ENGINE_TIMEOUT_MS.chat);
    expect(ENGINE_TIMEOUT_MS.chat).toBeLessThan(180_000);
  });

  it("maps a timed-out chat to a delivery-uncertain 504 using the chat budget", async () => {
    const pending = postChat(chatRequest(JSON.stringify({ message: "look" })));
    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalled());
    timeoutController.abort(new DOMException("timed out", "TimeoutError"));
    const response = await pending;

    expect(timeoutMs).toEqual([ENGINE_TIMEOUT_MS.chat]);
    expect(response.status).toBe(504);
    expect(await response.json()).toEqual({ error: "Backend request timed out" });
    const init = vi.mocked(global.fetch).mock.calls[0][1] as RequestInit;
    expect((init.headers as Headers).get("Idempotency-Key")).toBe(KEY);
  });

  it("uses the campaign-create budget and maps its timeout to 504", async () => {
    const pending = postCampaign(
      new Request("http://localhost:3000/api/campaign", { method: "POST" })
    );
    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalled());
    timeoutController.abort(new DOMException("timed out", "TimeoutError"));
    const response = await pending;

    expect(timeoutMs).toEqual([ENGINE_TIMEOUT_MS.campaignCreate]);
    expect(response.status).toBe(504);
  });

  it("applies the short read budget by default and maps its timeout to 504", async () => {
    const pending = getCampaigns();
    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalled());
    timeoutController.abort(new DOMException("timed out", "TimeoutError"));
    const response = await pending;

    expect(timeoutMs).toEqual([ENGINE_TIMEOUT_MS.read]);
    expect(response.status).toBe(504);
  });

  it.each([
    ["chat", () => postChat(chatRequest(JSON.stringify({ message: "look" })))],
    ["campaign list", () => getCampaigns()],
  ])("maps a timeout while reading the engine %s response body to 504", async (_label, call) => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.reject(new DOMException("timed out", "TimeoutError")),
    } as unknown as Response);

    const response = await call();

    expect(response.status).toBe(504);
    expect(await response.json()).toEqual({ error: "Backend request timed out" });
  });

  it("keeps a malformed engine body (not a timeout) as an unexpected 500", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.reject(new SyntaxError("Unexpected token")),
    } as unknown as Response);

    const response = await getCampaigns();

    expect(response.status).toBe(500);
  });

  it("does not report a caller-initiated abort as an engine timeout", async () => {
    const caller = new AbortController();
    const pending = fetchEngineAsUser("/api/campaigns", "user-1", { signal: caller.signal });
    const settled = pending.catch((error: unknown) => error);
    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalled());
    caller.abort(new Error("caller cancelled"));

    const error = await settled;
    expect((error as Error).name).not.toBe("InternalEngineTimeoutError");
    expect((error as Error).message).toBe("caller cancelled");
  });

  it("does not turn an ordinary engine network failure into a timeout", async () => {
    vi.mocked(global.fetch).mockRejectedValueOnce(new TypeError("fetch failed"));
    const response = await getCampaigns();

    expect(response.status).toBe(500);
  });
});
