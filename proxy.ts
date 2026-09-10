import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// The legacy Cloud Run frontend hostname (e.g.
// haunted-halls-frontend-<project-number>.<region>.run.app) is no longer a
// valid entry point now that NEXTAUTH_URL and Google OAuth are configured for
// the custom domain. Redirect it to the canonical host instead of leaving it
// reachable with a broken sign-in flow.
const LEGACY_HOST_SUFFIX = ".run.app";
const DEFAULT_CANONICAL_HOST = "haunted-halls.tesolin.us";

// NEXTAUTH_URL is the same authoritative, server-side deployment fact that
// Terraform sets to the canonical custom domain (see
// infra/terraform/locals.tf `frontend_canonical_url`) and that lib/route-auth.ts
// already trusts. Falling back to the hardcoded canonical host guards against
// a missing/invalid/legacy NEXTAUTH_URL ever causing a redirect loop.
function resolveCanonicalHost(): string {
  const configuredUrl = process.env.NEXTAUTH_URL?.trim();

  if (configuredUrl) {
    try {
      const { hostname } = new URL(configuredUrl);
      if (hostname && !hostname.endsWith(LEGACY_HOST_SUFFIX)) {
        return hostname;
      }
    } catch {
      // Ignore an invalid NEXTAUTH_URL and fall back to the hardcoded host.
    }
  }

  return DEFAULT_CANONICAL_HOST;
}

// Cloud Run terminates TLS in front of the container and forwards the
// original public hostname the client requested via the Host header (and
// x-forwarded-host). request.nextUrl.hostname instead reflects the address
// Next.js is bound to internally, so it cannot be used to detect which
// public hostname served the request.
function resolveRequestHostname(request: NextRequest): string {
  const forwardedHost = request.headers
    .get("x-forwarded-host")
    ?.split(",", 1)[0]
    ?.trim();
  const host = forwardedHost || request.headers.get("host")?.trim() || "";

  const hostname = host.startsWith("[")
    ? host.slice(1, host.indexOf("]"))
    : host.replace(/:\d+$/, "");

  return hostname.toLowerCase();
}

export function proxy(request: NextRequest) {
  const requestHostname = resolveRequestHostname(request);

  if (!requestHostname.endsWith(LEGACY_HOST_SUFFIX)) {
    return NextResponse.next();
  }

  const canonicalHost = resolveCanonicalHost();
  const destination = new URL(`https://${canonicalHost}`);
  destination.pathname = request.nextUrl.pathname;
  destination.search = request.nextUrl.search;

  return NextResponse.redirect(destination, 308);
}

export const config = {
  // Never redirect the Cloud Run startup/health probe: it must keep returning
  // /api/health directly regardless of which hostname it is reached on.
  matcher: ["/((?!api/health(?:/)?$).*)"],
};
