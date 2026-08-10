import { NextResponse } from "next/server";

const DEFAULT_ENGINE_BASE_URL = "http://localhost:8000";
const MIN_INTERNAL_ENGINE_SERVICE_TOKEN_LENGTH = 64;
export const INTERNAL_ENGINE_USER_ID_HEADER = "X-Haunted-Halls-User-Id";
const INTERNAL_ENGINE_SERVICE_TOKEN_PLACEHOLDERS = new Set([
  "replace-with-internal-engine-token",
  "generate-with-openssl-do-not-commit",
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

function createServiceHeaders(headers?: HeadersInit) {
  const requestHeaders = new Headers(headers);
  requestHeaders.delete("authorization");
  requestHeaders.delete(INTERNAL_ENGINE_USER_ID_HEADER);
  requestHeaders.set("Authorization", `Bearer ${getInternalEngineServiceToken()}`);
  return requestHeaders;
}

function createPublicHeaders(headers?: HeadersInit) {
  const requestHeaders = new Headers(headers);
  requestHeaders.delete("authorization");
  requestHeaders.delete(INTERNAL_ENGINE_USER_ID_HEADER);
  return requestHeaders;
}

function normalizeInternalUserId(internalUserId: string) {
  const normalized = internalUserId.trim();
  if (!normalized) {
    throw new InternalEngineUserContextError("internal user context is missing");
  }
  return normalized;
}

function createUserScopedHeaders(internalUserId: string, headers?: HeadersInit) {
  const requestHeaders = createServiceHeaders(headers);
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
    headers: createServiceHeaders(init.headers),
  });
}

export async function fetchEngineAsUser(
  input: string | URL,
  internalUserId: string,
  init: RequestInit = {}
) {
  return fetch(resolveEngineUrl(input), {
    ...init,
    headers: createUserScopedHeaders(internalUserId, init.headers),
  });
}

export async function fetchEnginePublic(input: string | URL, init: RequestInit = {}) {
  return fetch(resolveEngineUrl(input), {
    ...init,
    headers: createPublicHeaders(init.headers),
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

  const text = await response.text();
  return NextResponse.json(
    { error: "Backend request failed", details: text },
    { status: response.status }
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

export function getMaxInputCharacters() {
  const parsed = Number.parseInt(process.env.MAX_INPUT_CHARACTERS ?? "2000", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 2000;
}
