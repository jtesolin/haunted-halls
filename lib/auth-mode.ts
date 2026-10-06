export type AuthMode = "google" | "iap" | "e2e";

export function getAuthMode(): AuthMode {
  const mode = process.env.AUTH_MODE;
  if (mode === undefined) {
    // Preserve existing loopback E2E stacks that predate AUTH_MODE.
    return process.env.E2E_AUTH_ENABLED?.trim().toLowerCase() === "true" ? "e2e" : "google";
  }
  if (mode === "google" || mode === "iap" || mode === "e2e") {
    return mode;
  }
  throw new Error("AUTH_MODE must be google, iap, or e2e");
}
