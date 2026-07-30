import {
  fetchEngine,
  InternalEngineConfigurationError,
  InternalEngineOriginError,
} from "@/lib/engine";

export const GOOGLE_IDENTITY_PROVIDER = "google";
export const CANONICAL_GOOGLE_ISSUER = "https://accounts.google.com";
const ACCEPTED_GOOGLE_ISSUERS = new Set([CANONICAL_GOOGLE_ISSUER, "accounts.google.com"]);
const INTERNAL_RESOLVE_PATH = "/internal/auth/users/resolve";

type IdentityProfile = {
  identityProvider: "google";
  providerIssuer: string;
  providerSubject: string;
  email: string;
  emailVerified: true;
  displayName?: string | null;
  avatarUrl?: string | null;
};

type ResolveUserResponse = {
  user_id: string;
};

export class InternalUserResolutionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InternalUserResolutionError";
  }
}

function normalizeGoogleIssuer(issuer: string): string {
  const normalized = issuer.trim();
  if (!ACCEPTED_GOOGLE_ISSUERS.has(normalized)) {
    throw new InternalUserResolutionError("Unsupported Google issuer");
  }
  return CANONICAL_GOOGLE_ISSUER;
}

function normalizeRequiredString(value: unknown, fieldName: string, maxLength: number): string {
  if (typeof value !== "string") {
    throw new InternalUserResolutionError(`${fieldName} is required`);
  }

  const normalized = value.trim();
  if (!normalized) {
    throw new InternalUserResolutionError(`${fieldName} is required`);
  }

  if (normalized.length > maxLength) {
    throw new InternalUserResolutionError(`${fieldName} exceeds ${maxLength} characters`);
  }

  return normalized;
}

function normalizeOptionalString(value: unknown, maxLength: number): string | null {
  if (typeof value !== "string") {
    return null;
  }

  const normalized = value.trim();
  if (!normalized) {
    return null;
  }

  return normalized.length <= maxLength ? normalized : normalized.slice(0, maxLength);
}

function normalizeOptionalUrl(value: unknown): string | null {
  const normalized = normalizeOptionalString(value, 2048);
  if (!normalized) {
    return null;
  }

  try {
    const parsed = new URL(normalized);
    return parsed.toString();
  } catch {
    return null;
  }
}

function normalizeEmail(email: unknown): string {
  const normalized = normalizeRequiredString(email, "email", 320);
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalized)) {
    throw new InternalUserResolutionError("email must be valid");
  }
  return normalized;
}

function getGoogleIssuer(profile: Record<string, unknown>): string {
  const profileIssuer = typeof profile.iss === "string" ? profile.iss : CANONICAL_GOOGLE_ISSUER;
  return normalizeGoogleIssuer(profileIssuer);
}

export function buildGoogleIdentityProfile(input: {
  account: { provider: string; providerAccountId?: string | null };
  profile: Record<string, unknown>;
}): IdentityProfile {
  if (input.account.provider !== GOOGLE_IDENTITY_PROVIDER) {
    throw new InternalUserResolutionError("Unsupported identity provider");
  }

  const subjectFromClaims = typeof input.profile.sub === "string" ? input.profile.sub : "";
  const subject = normalizeRequiredString(
    subjectFromClaims || input.account.providerAccountId,
    "provider_subject",
    255
  );

  const emailVerified = input.profile.email_verified;
  if (emailVerified !== true) {
    throw new InternalUserResolutionError("email_verified must be true");
  }

  return {
    identityProvider: GOOGLE_IDENTITY_PROVIDER,
    providerIssuer: getGoogleIssuer(input.profile),
    providerSubject: subject,
    email: normalizeEmail(input.profile.email),
    emailVerified: true,
    displayName: normalizeOptionalString(input.profile.name, 255),
    avatarUrl: normalizeOptionalUrl(input.profile.picture),
  };
}

export async function resolveInternalUserId(identity: IdentityProfile): Promise<string> {
  try {
    const response = await fetchEngine(INTERNAL_RESOLVE_PATH, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        identity_provider: identity.identityProvider,
        provider_issuer: identity.providerIssuer,
        provider_subject: identity.providerSubject,
        email: identity.email,
        email_verified: identity.emailVerified,
        display_name: identity.displayName ?? null,
        avatar_url: identity.avatarUrl ?? null,
      }),
    });

    if (!response.ok) {
      throw new InternalUserResolutionError("Internal user resolution request failed");
    }

    const data = (await response.json()) as Partial<ResolveUserResponse>;
    const userId = typeof data.user_id === "string" ? data.user_id.trim() : "";
    if (!userId) {
      throw new InternalUserResolutionError("Internal user resolution response was invalid");
    }

    return userId;
  } catch (error) {
    if (
      error instanceof InternalUserResolutionError ||
      error instanceof InternalEngineConfigurationError ||
      error instanceof InternalEngineOriginError
    ) {
      throw error;
    }

    throw new InternalUserResolutionError("Internal user resolution failed");
  }
}
