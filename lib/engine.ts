import { NextResponse } from "next/server";
import { GoogleAuth } from "google-auth-library";
import type { IdTokenClient } from "google-auth-library";

const DEFAULT_ENGINE_BASE_URL = "http://localhost:8000";
const MIN_INTERNAL_ENGINE_SERVICE_TOKEN_LENGTH = 64;
const ENGINE_ID_TOKEN_AUDIENCE_ENV = "ENGINE_ID_TOKEN_AUDIENCE";
export const INTERNAL_ENGINE_USER_ID_HEADER = "X-Haunted-Halls-User-Id";
const INTERNAL_ENGINE_SERVICE_TOKEN_PLACEHOLDERS = new Set([
  "replace-with-internal-engine-token",
  "generate-with-openssl-do-not-commit",
]);
let googleAuth: GoogleAuth | undefined;
const idTokenClients = new Map<string, Promise<IdTokenClient>>();
const PUBLIC_ENGINE_ERROR_CODES = new Set([
  "daily_request_limit",
  "daily_token_limit",
  "campaign_turn_limit",
  "max_campaigns",
  "temporary_rate_limit",
]);

export class InternalEngineConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InternalEngineConfigurationError";
  }
}

export class InternalEngineOriginError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InternalEngineOriginError";
  }
}

export class InternalEngineUserContextError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InternalEngineUserContextError";
  }
}

export function getEngineBaseUrl() {
  return process.env.ENGINE_BASE_URL?.trim() || DEFAULT_ENGINE_BASE_URL;
}

export function getInternalEngineServiceToken() {
  const token = process.env.INTERNAL_ENGINE_SERVICE_TOKEN?.trim();

  if (!token) {
    throw new InternalEngineConfigurationError("INTERNAL_ENGINE_SERVICE_TOKEN is not configured");
  }

  if (
    token.length < MIN_INTERNAL_ENGINE_SERVICE_TOKEN_LENGTH ||
    INTERNAL_ENGINE_SERVICE_TOKEN_PLACEHOLDERS.has(token)
  ) {
    throw new InternalEngineConfigurationError(
      "INTERNAL_ENGINE_SERVICE_TOKEN must be at least 32 bytes of random entropy"
    );
  }

  return token;
}

async function createCloudRunIdentityHeader() {
  const audience = process.env[ENGINE_ID_TOKEN_AUDIENCE_ENV]?.trim();
  if (!audience) {
    return null;
  }

  if (!googleAuth) {
    googleAuth = new GoogleAuth();
  }

  let clientPromise = idTokenClients.get(audience);
  if (!clientPromise) {
    clientPromise = (async () => googleAuth!.getIdTokenClient(audience))();
    idTokenClients.set(audience, clientPromise);
  }

  try {
    const client = await clientPromise;
    const identityHeaders = await client.getRequestHeaders();
    const authorization = identityHeaders.get("authorization");

    if (authorization) {
      return authorization;
    }
  } catch {
    idTokenClients.delete(audience);
  }

  throw new InternalEngineConfigurationError(
    `Cloud Run identity token could not be acquired for audience ${audience}`
  );
}

async function createServiceHeaders(headers?: HeadersInit) {
  const requestHeaders = new Headers(headers);
  requestHeaders.delete("authorization");
  requestHeaders.delete("x-serverless-authorization");
  requestHeaders.delete(INTERNAL_ENGINE_USER_ID_HEADER);
  requestHeaders.set("Authorization", `Bearer ${getInternalEngineServiceToken()}`);
  const cloudRunAuthorization = await createCloudRunIdentityHeader();
  if (cloudRunAuthorization) {
    requestHeaders.set("X-Serverless-Authorization", cloudRunAuthorization);
  }
  return requestHeaders;
}

async function createPublicHeaders(headers?: HeadersInit) {
  const requestHeaders = new Headers(headers);
  requestHeaders.delete("authorization");
  requestHeaders.delete("x-serverless-authorization");
  requestHeaders.delete(INTERNAL_ENGINE_USER_ID_HEADER);
  const cloudRunAuthorization = await createCloudRunIdentityHeader();
  if (cloudRunAuthorization) {
    requestHeaders.set("X-Serverless-Authorization", cloudRunAuthorization);
  }
  return requestHeaders;
}

function normalizeInternalUserId(internalUserId: string) {
  const normalized = internalUserId.trim();
  if (!normalized) {
    throw new InternalEngineUserContextError("internal user context is missing");
  }
  return normalized;
}

async function createUserScopedHeaders(internalUserId: string, headers?: HeadersInit) {
  const requestHeaders = await createServiceHeaders(headers);
  requestHeaders.set(INTERNAL_ENGINE_USER_ID_HEADER, normalizeInternalUserId(internalUserId));
  return requestHeaders;
}

function resolveEngineUrl(input: string | URL) {
  const engineBaseUrl = getEngineBaseUrl();
  const url = input instanceof URL ? new URL(input.toString()) : new URL(input, engineBaseUrl);

  if (url.origin !== new URL(engineBaseUrl).origin) {
    throw new InternalEngineOriginError(
      "Refusing to send internal credentials to a non-engine origin"
    );
  }

  return url;
}

export async function fetchEngineAsService(input: string | URL, init: RequestInit = {}) {
  return fetch(resolveEngineUrl(input), {
    ...init,
    headers: await createServiceHeaders(init.headers),
  });
}

export async function fetchEngineAsUser(
  input: string | URL,
  internalUserId: string,
  init: RequestInit = {}
) {
  return fetch(resolveEngineUrl(input), {
    ...init,
    headers: await createUserScopedHeaders(internalUserId, init.headers),
  });
}

export async function fetchEnginePublic(input: string | URL, init: RequestInit = {}) {
  return fetch(resolveEngineUrl(input), {
    ...init,
    headers: await createPublicHeaders(init.headers),
  });
}

export const fetchEngine = fetchEngineAsService;

export async function respondWithEngineError(
  response: Response,
  context: string,
  fallbackError: string
) {
  if (response.status === 401 || response.status === 403) {
    console.error(`${context}: engine rejected authenticated internal request context`, {
      status: response.status,
    });
    return NextResponse.json({ error: fallbackError }, { status: 502 });
  }

  let detail: string | null = null;
  let code: string | null = null;
  let retryable: boolean | null = null;
  let retryAt: string | null = null;

  try {
    const payload = (await response.json()) as {
      detail?: unknown;
      error?: unknown;
      code?: unknown;
      retryable?: unknown;
      retry_at?: unknown;
    };
    const structuredDetail = payload.detail && typeof payload.detail === "object"
      ? payload.detail as Record<string, unknown>
      : null;
    const publicDetail = structuredDetail?.detail ?? payload.detail;

    if (typeof publicDetail === "string" && publicDetail.trim()) {
      detail = publicDetail.trim();
    } else if (typeof payload.error === "string" && payload.error.trim()) {
      detail = payload.error.trim();
    }

    const candidateCode = structuredDetail?.code ?? payload.code;
    if (typeof candidateCode === "string" && PUBLIC_ENGINE_ERROR_CODES.has(candidateCode)) {
      code = candidateCode;
    }

    const candidateRetryable = structuredDetail?.retryable ?? payload.retryable;
    if (typeof candidateRetryable === "boolean" && code !== null) {
      retryable = candidateRetryable;
    }

    const candidateRetryAt = structuredDetail?.retry_at ?? payload.retry_at;
    if (typeof candidateRetryAt === "string" && code !== null && candidateRetryAt.trim()) {
      retryAt = candidateRetryAt.trim();
    }
  } catch {
    detail = null;
  }

  if (response.status === 404) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  if (response.status === 400 || response.status === 422 || response.status === 429) {
    const publicError: Record<string, string | boolean> = {
      error: detail ?? "Backend request failed",
    };
    if (code !== null) {
      publicError.code = code;
    }
    if (retryable !== null) {
      publicError.retryable = retryable;
    }
    if (retryAt !== null) {
      publicError.retry_at = retryAt;
    }

    return NextResponse.json(
      publicError,
      { status: response.status }
    );
  }

  console.error(`${context}: engine request failed`, {
    status: response.status,
  });

  return NextResponse.json(
    { error: "Backend request failed" },
    { status: response.status >= 500 ? 502 : response.status }
  );
}

export function isInternalEngineRequestError(
  error: unknown
): error is InternalEngineConfigurationError | InternalEngineOriginError | InternalEngineUserContextError {
  return (
    error instanceof InternalEngineConfigurationError ||
    error instanceof InternalEngineOriginError ||
    error instanceof InternalEngineUserContextError
  );
}

export function respondWithInternalEngineError(context: string, error: unknown) {
  console.error(
    `${context}: ${error instanceof Error ? error.message : "internal engine request failed"}`
  );

  return NextResponse.json(
    { error: "Backend service unavailable" },
    { status: 503 }
  );
}

export function respondWithUnexpectedProxyError(context: string) {
  console.error(`${context}: unexpected proxy failure`);

  return NextResponse.json(
    { error: "Unable to process request" },
    { status: 500 }
  );
}

export function getMaxInputCharacters() {
  const parsed = Number.parseInt(process.env.MAX_INPUT_CHARACTERS ?? "2000", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 2000;
}
