import { expect, test as setup } from "@playwright/test";

const AUTH_FILE = "playwright/.auth/user.json";

/**
 * Authenticates through the real local NextAuth HTTP endpoints using the guarded,
 * loopback-only, test-only "e2e" credentials provider (see lib/auth.ts / lib/e2e-auth.ts).
 *
 * This intentionally does not automate any Google UI. It acquires a NextAuth CSRF
 * token, submits the e2e credentials-provider callback, verifies the resulting
 * session via /api/auth/session, and saves the authenticated browser storage state
 * for reuse by the authenticated Chromium project.
 */
setup("authenticate as the fixed playwright-e2e identity", async ({ page, baseURL }) => {
  const origin = baseURL ?? "http://localhost:3000";

  const csrfResponse = await page.request.get(`${origin}/api/auth/csrf`);
  expect(csrfResponse.ok()).toBeTruthy();
  const { csrfToken } = (await csrfResponse.json()) as { csrfToken: string };
  expect(csrfToken).toBeTruthy();

  const callbackResponse = await page.request.post(`${origin}/api/auth/callback/e2e`, {
    form: {
      csrfToken,
      json: "true",
    },
  });
  expect(callbackResponse.ok()).toBeTruthy();

  const sessionResponse = await page.request.get(`${origin}/api/auth/session`);
  expect(sessionResponse.ok()).toBeTruthy();
  const session = (await sessionResponse.json()) as { user?: { email?: string } };
  expect(session.user?.email).toBe("playwright-e2e@example.com");

  await page.context().storageState({ path: AUTH_FILE });
});
