/* @vitest-environment node */

// next ships this compiled dependency without type declarations; it is used
// here only to mirror Next's own matcher-to-regexp semantics in tests.
// @ts-expect-error -- no bundled types for next/dist/compiled/path-to-regexp
import { pathToRegexp } from "next/dist/compiled/path-to-regexp";
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it } from "vitest";
import { config, proxy } from "@/proxy";

const ORIGINAL_NEXTAUTH_URL = process.env.NEXTAUTH_URL;

afterEach(() => {
  if (ORIGINAL_NEXTAUTH_URL === undefined) {
    delete process.env.NEXTAUTH_URL;
  } else {
    process.env.NEXTAUTH_URL = ORIGINAL_NEXTAUTH_URL;
  }
});

// Cloud Run (via the Google Front End) forwards the original public hostname
// the client requested as the request's Host header, so tests must set it
// explicitly the same way rather than relying on the request's own URL.
function makeRequest(url: string, hostHeader: string) {
  return new NextRequest(url, { headers: { host: hostHeader } });
}

describe("proxy legacy run.app redirect", () => {
  it("redirects the legacy run.app hostname to the custom domain", () => {
    process.env.NEXTAUTH_URL = "https://haunted-halls.tesolin.us";

    const request = makeRequest(
      "https://frontend.internal/",
      "haunted-halls-frontend-458395246135.us-east1.run.app",
    );
    const response = proxy(request);

    expect(response.status).toBe(308);
    expect(response.headers.get("location")).toBe("https://haunted-halls.tesolin.us/");
  });

  it("preserves the request path when redirecting", () => {
    process.env.NEXTAUTH_URL = "https://haunted-halls.tesolin.us";

    const request = makeRequest(
      "https://haunted-halls-frontend-458395246135.us-east1.run.app/foo",
      "haunted-halls-frontend-458395246135.us-east1.run.app",
    );
    const response = proxy(request);

    expect(response.headers.get("location")).toBe("https://haunted-halls.tesolin.us/foo");
  });

  it("preserves the query string when redirecting", () => {
    process.env.NEXTAUTH_URL = "https://haunted-halls.tesolin.us";

    const request = makeRequest(
      "https://haunted-halls-frontend-458395246135.us-east1.run.app/foo?bar=baz",
      "haunted-halls-frontend-458395246135.us-east1.run.app",
    );
    const response = proxy(request);

    expect(response.headers.get("location")).toBe(
      "https://haunted-halls.tesolin.us/foo?bar=baz",
    );
  });

  it("keeps a protocol-relative-looking path on the canonical host", () => {
    process.env.NEXTAUTH_URL = "https://haunted-halls.tesolin.us";

    const request = makeRequest(
      "https://frontend.internal//evil.example/path?bar=baz",
      "haunted-halls-frontend-458395246135.us-east1.run.app",
    );
    const response = proxy(request);
    const location = response.headers.get("location");

    expect(response.status).toBe(308);
    expect(new URL(location ?? "").hostname).toBe("haunted-halls.tesolin.us");
    expect(new URL(location ?? "").pathname).toBe("//evil.example/path");
    expect(new URL(location ?? "").search).toBe("?bar=baz");
  });

  it("does not redirect requests already on the canonical custom domain", () => {
    process.env.NEXTAUTH_URL = "https://haunted-halls.tesolin.us";

    const request = makeRequest(
      "https://haunted-halls.tesolin.us/foo?bar=baz",
      "haunted-halls.tesolin.us",
    );
    const response = proxy(request);

    expect(response.headers.get("location")).toBeNull();
  });

  it("does not redirect localhost/local development requests", () => {
    process.env.NEXTAUTH_URL = "http://localhost:3000";

    const request = makeRequest("http://localhost:3000/campaign", "localhost:3000");
    const response = proxy(request);

    expect(response.headers.get("location")).toBeNull();
  });

  it("falls back to the hardcoded canonical host when NEXTAUTH_URL is missing", () => {
    delete process.env.NEXTAUTH_URL;

    const request = makeRequest(
      "https://haunted-halls-frontend-458395246135.us-east1.run.app/foo",
      "haunted-halls-frontend-458395246135.us-east1.run.app",
    );
    const response = proxy(request);

    expect(response.headers.get("location")).toBe("https://haunted-halls.tesolin.us/foo");
  });

  it("falls back to the hardcoded canonical host when NEXTAUTH_URL is itself a run.app URL", () => {
    process.env.NEXTAUTH_URL =
      "https://haunted-halls-frontend-458395246135.us-east1.run.app";

    const request = makeRequest(
      "https://haunted-halls-frontend-458395246135.us-east1.run.app/foo",
      "haunted-halls-frontend-458395246135.us-east1.run.app",
    );
    const response = proxy(request);

    expect(response.headers.get("location")).toBe("https://haunted-halls.tesolin.us/foo");
  });

  it("falls back to the hardcoded canonical host when NEXTAUTH_URL is invalid", () => {
    process.env.NEXTAUTH_URL = "not-a-url";

    const request = makeRequest(
      "https://haunted-halls-frontend-458395246135.us-east1.run.app/foo",
      "haunted-halls-frontend-458395246135.us-east1.run.app",
    );
    const response = proxy(request);

    expect(response.headers.get("location")).toBe("https://haunted-halls.tesolin.us/foo");
  });

  it("uses x-forwarded-host over the Host header when both are present", () => {
    process.env.NEXTAUTH_URL = "https://haunted-halls.tesolin.us";

    const request = new NextRequest(
      "https://internal-lb.local/foo?bar=baz",
      {
        headers: {
          host: "internal-lb.local",
          "x-forwarded-host": "haunted-halls-frontend-458395246135.us-east1.run.app",
        },
      },
    );
    const response = proxy(request);

    expect(response.headers.get("location")).toBe(
      "https://haunted-halls.tesolin.us/foo?bar=baz",
    );
  });

  it("uses the first comma-separated x-forwarded-host value", () => {
    process.env.NEXTAUTH_URL = "https://haunted-halls.tesolin.us";

    const request = new NextRequest("https://internal-lb.local/foo", {
      headers: {
        host: "internal-lb.local",
        "x-forwarded-host":
          " haunted-halls-frontend-458395246135.us-east1.run.app:443, internal-proxy.example",
      },
    });
    const response = proxy(request);

    expect(response.status).toBe(308);
    expect(response.headers.get("location")).toBe("https://haunted-halls.tesolin.us/foo");
  });
});

describe("proxy matcher", () => {
  const matcherSource = config.matcher[0];
  const matcherRegexp = pathToRegexp(matcherSource);

  it("excludes /api/health so Cloud Run's health/startup probe is never redirected", () => {
    expect(matcherRegexp.test("/api/health")).toBe(false);
  });

  it("still applies to similarly prefixed paths such as /api/healthz", () => {
    expect(matcherRegexp.test("/api/healthz")).toBe(true);
  });

  it("still applies to descendants such as /api/health/debug", () => {
    expect(matcherRegexp.test("/api/health/debug")).toBe(true);
  });

  it("still applies to unrelated API/BFF and page routes", () => {
    expect(matcherRegexp.test("/")).toBe(true);
    expect(matcherRegexp.test("/campaign")).toBe(true);
    expect(matcherRegexp.test("/api/chat")).toBe(true);
    expect(matcherRegexp.test("/api/auth/callback/google")).toBe(true);
  });
});
