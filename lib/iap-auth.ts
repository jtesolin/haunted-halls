import { OAuth2Client } from "google-auth-library";
import {
  buildGoogleIdentityProfile,
  CANONICAL_GOOGLE_ISSUER,
} from "@/lib/internal-user-resolution";

export const IAP_PROVIDER_ID = "iap";
export const IAP_ISSUER = "https://cloud.google.com/iap";
const client = new OAuth2Client();

export function getIapExpectedAudience(): string {
  const audience = process.env.IAP_EXPECTED_AUDIENCE?.trim();
  if (!audience) {
    throw new Error("IAP_EXPECTED_AUDIENCE is required for IAP authentication");
  }
  return audience;
}

export async function verifyIapIdentity(assertion: unknown, audience: string) {
  try {
    if (typeof assertion !== "string" || !assertion.trim()) {
      throw new Error("Missing IAP assertion");
    }
    const { pubkeys } = await client.getIapPublicKeysAsync();
    const ticket = await client.verifySignedJwtWithCertsAsync(
      assertion,
      pubkeys,
      audience,
      [IAP_ISSUER]
    );
    const payload = ticket.getPayload();
    if (
      !payload ||
      payload.iss !== IAP_ISSUER ||
      payload.aud !== audience ||
      typeof payload.sub !== "string" ||
      !payload.sub.trim() ||
      payload.sub !== payload.sub.trim() ||
      !Number.isFinite(payload.iat) ||
      !Number.isFinite(payload.exp) ||
      payload.exp <= payload.iat
    ) {
      throw new Error("Invalid IAP claims");
    }
    if (
      "nbf" in payload &&
      (typeof payload.nbf !== "number" ||
        !Number.isFinite(payload.nbf) ||
        payload.nbf > Date.now() / 1000)
    ) {
      throw new Error("Invalid IAP not-before time");
    }

    // Preview compatibility adapter: the JWT was verified as IAP, not Google
    // OAuth. The current engine resolver accepts only this Google-shaped contract.
    return buildGoogleIdentityProfile({
      account: { provider: "google" },
      profile: {
        iss: CANONICAL_GOOGLE_ISSUER,
        sub: `iap:${payload.sub}`,
        email: payload.email,
        email_verified: true,
      },
    });
  } catch {
    // Library verification errors can contain the raw JWT; never propagate them.
    throw new Error("IAP authentication failed");
  }
}
