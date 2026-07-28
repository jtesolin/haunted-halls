/* @vitest-environment node */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  InternalEngineConfigurationError,
  fetchEngine,
} from "@/lib/engine";

const TEST_INTERNAL_ENGINE_SERVICE_TOKEN =
  "test-internal-engine-service-token-0000000000000000000000000000000000";

const originalInternalEngineServiceToken = process.env.INTERNAL_ENGINE_SERVICE_TOKEN;
const originalEngineBaseUrl = process.env.ENGINE_BASE_URL;

describe("engine client", () => {
  beforeEach(() => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    vi.mocked(global.fetch).mockReset();
    process.env.INTERNAL_ENGINE_SERVICE_TOKEN = TEST_INTERNAL_ENGINE_SERVICE_TOKEN;
    process.env.ENGINE_BASE_URL = "http://localhost:8000";
  });

  afterEach(() => {
    if (originalInternalEngineServiceToken === undefined) {
      delete process.env.INTERNAL_ENGINE_SERVICE_TOKEN;
    } else {
      process.env.INTERNAL_ENGINE_SERVICE_TOKEN = originalInternalEngineServiceToken;
    }

    if (originalEngineBaseUrl === undefined) {
      delete process.env.ENGINE_BASE_URL;
    } else {
      process.env.ENGINE_BASE_URL = originalEngineBaseUrl;
    }
  });

  it("adds the configured bearer token and strips browser authorization", async () => {
    vi.mocked(global.fetch).mockResolvedValue(new Response("{}", { status: 200 }));

    await fetchEngine("/api/chat", {
      method: "POST",
      headers: {
        Authorization: "Bearer browser-token",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message: "look" }),
    });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [target, init] = vi.mocked(global.fetch).mock.calls[0];
    expect(String(target)).toBe("http://localhost:8000/api/chat");

    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe(`Bearer ${TEST_INTERNAL_ENGINE_SERVICE_TOKEN}`);
    expect(headers.get("authorization")).toBe(`Bearer ${TEST_INTERNAL_ENGINE_SERVICE_TOKEN}`);
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("refuses to send credentials to a non-engine origin", async () => {
    await expect(fetchEngine("https://example.com/api/chat")).rejects.toBeInstanceOf(Error);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("fails clearly when the internal token is missing", async () => {
    delete process.env.INTERNAL_ENGINE_SERVICE_TOKEN;

    await expect(fetchEngine("/api/chat")).rejects.toBeInstanceOf(
      InternalEngineConfigurationError
    );
    expect(global.fetch).not.toHaveBeenCalled();
  });
});