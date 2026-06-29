const DEFAULT_ENGINE_BASE_URL = "http://localhost:8000";

export function getEngineBaseUrl() {
  return process.env.ENGINE_BASE_URL?.trim() || DEFAULT_ENGINE_BASE_URL;
}

export function getEngineAuthHeaders(includeJsonContentType = false) {
  const token = process.env.INTERNAL_API_TOKEN?.trim();

  if (!token) {
    throw new Error("INTERNAL_API_TOKEN is not configured");
  }

  return {
    Authorization: `Bearer ${token}`,
    ...(includeJsonContentType ? { "Content-Type": "application/json" } : {}),
  };
}

export function getMaxInputCharacters() {
  const parsed = Number.parseInt(process.env.MAX_INPUT_CHARACTERS ?? "2000", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 2000;
}
