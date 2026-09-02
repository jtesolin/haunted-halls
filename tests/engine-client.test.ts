/* @vitest-environment node */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GoogleAuth } from "google-auth-library";
import {
  InternalEngineConfigurationError,
  INTERNAL_ENGINE_USER_ID_HEADER,
  fetchEngineAsService,
  fetchEngineAsUser,
  fetchEnginePublic,
} from "@/lib/engine";

vi.mock("google-auth-library", () => ({
  GoogleAuth: vi.fn(),
}));

const TEST_INTERNAL_ENGINE_SERVICE_TOKEN =
  "test-internal-engine-service-token-0000000000000000000000000000000000";

const originalInternalEngineServiceToken = process.env.INTERNAL_ENGINE_SERVICE_TOKEN;
const originalEngineBaseUrl = process.env.ENGINE_BASE_URL;
const originalEngineIdTokenAudience = process.env.ENGINE_ID_TOKEN_AUDIENCE;
const getRequestHeaders = vi.fn();
const getIdTokenClient = vi.fn();

describe("engine client", () => {
  beforeEach(() => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    vi.mocked(global.fetch).mockReset();
    process.env.INTERNAL_ENGINE_SERVICE_TOKEN = TEST_INTERNAL_ENGINE_SERVICE_TOKEN;
    process.env.ENGINE_BASE_URL = "http://localhost:8000";
    delete process.env.ENGINE_ID_TOKEN_AUDIENCE;
    getRequestHeaders.mockResolvedValue(new Headers({ Authorization: "Bearer google-id-token" }));
    getIdTokenClient.mockResolvedValue({ getRequestHeaders });
    vi.mocked(GoogleAuth).mockImplementation(
      class {
        getIdTokenClient = getIdTokenClient;
      } as unknown as typeof GoogleAuth
    );
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

    if (originalEngineIdTokenAudience === undefined) {
      delete process.env.ENGINE_ID_TOKEN_AUDIENCE;
    } else {
      process.env.ENGINE_ID_TOKEN_AUDIENCE = originalEngineIdTokenAudience;
    }
  });

  it("adds the configured bearer token for service-only requests and strips browser auth headers", async () => {
    vi.mocked(global.fetch).mockResolvedValue(new Response("{}", { status: 200 }));

    await fetchEngineAsService("/api/chat", {
      method: "POST",
      headers: {
        Authorization: "Bearer browser-token",
        [INTERNAL_ENGINE_USER_ID_HEADER]: "user_spoofed",
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
    expect(headers.get("X-Serverless-Authorization")).toBeNull();
    expect(headers.get(INTERNAL_ENGINE_USER_ID_HEADER)).toBeNull();
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("preserves application auth and adds a Cloud Run ID token when configured", async () => {
    process.env.ENGINE_ID_TOKEN_AUDIENCE = "https://haunted-halls-engine-123.us-east1.run.app";
    vi.mocked(global.fetch).mockResolvedValue(new Response("{}", { status: 200 }));

    await fetchEngineAsService("/api/chat", {
      headers: {
        Authorization: "Bearer browser-token",
        "X-Serverless-Authorization": "Bearer browser-google-token",
      },
    });

    const [, init] = vi.mocked(global.fetch).mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe(`Bearer ${TEST_INTERNAL_ENGINE_SERVICE_TOKEN}`);
    expect(headers.get("X-Serverless-Authorization")).toBe("Bearer google-id-token");
    expect(getIdTokenClient).toHaveBeenCalledWith(
      "https://haunted-halls-engine-123.us-east1.run.app"
    );
  });

  it("adds bearer and trusted internal user context for user-scoped requests", async () => {
    vi.mocked(global.fetch).mockResolvedValue(new Response("{}", { status: 200 }));

    await fetchEngineAsUser("/api/chat", "user_0123456789abcdef0123456789abcdef", {
      method: "POST",
      headers: {
        Authorization: "Bearer browser-token",
        [INTERNAL_ENGINE_USER_ID_HEADER]: "user_browser_supplied",
      },
    });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [, init] = vi.mocked(global.fetch).mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe(`Bearer ${TEST_INTERNAL_ENGINE_SERVICE_TOKEN}`);
    expect(headers.get(INTERNAL_ENGINE_USER_ID_HEADER)).toBe(
      "user_0123456789abcdef0123456789abcdef"
    );
    expect(headers.get("X-Serverless-Authorization")).toBeNull();
  });

  it("adds Cloud Run IAM auth to public engine requests without application auth", async () => {
    process.env.ENGINE_ID_TOKEN_AUDIENCE = "https://haunted-halls-engine-123.us-east1.run.app";
    vi.mocked(global.fetch).mockResolvedValue(new Response("{}", { status: 200 }));

    await fetchEnginePublic("/health", {
      headers: {
        Authorization: "Bearer browser-token",
        "X-Serverless-Authorization": "Bearer browser-google-token",
      },
    });

    const [, init] = vi.mocked(global.fetch).mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBeNull();
    expect(headers.get("X-Serverless-Authorization")).toBe("Bearer google-id-token");
  });

  it("refuses to send credentials to a non-engine origin", async () => {
    await expect(fetchEngineAsService("https://example.com/api/chat")).rejects.toBeInstanceOf(Error);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("fails clearly when the internal token is missing", async () => {
    delete process.env.INTERNAL_ENGINE_SERVICE_TOKEN;

    await expect(fetchEngineAsService("/api/chat")).rejects.toBeInstanceOf(
      InternalEngineConfigurationError
    );
    expect(global.fetch).not.toHaveBeenCalled();
  });
});