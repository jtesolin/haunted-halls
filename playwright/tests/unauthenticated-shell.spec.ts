import { expect, test } from "@playwright/test";

// Unauthenticated shell must never click through to Google or exercise the OAuth
// browser flow. It uses empty storage state, independent of the authenticated
// Chromium project's saved playwright/.auth/user.json.
test.use({ storageState: { cookies: [], origins: [] } });

test.describe("unauthenticated shell", () => {
  test("shows signed-out campaign prompt, Google sign-in control, and disabled command input", async ({
    page,
  }) => {
    await page.goto("/");

    await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeVisible();
    await expect(page.getByText("Sign in to start or continue a campaign.")).toBeVisible();

    const commandInput = page.getByLabel("Enter your command");
    await expect(commandInput).toBeDisabled();
  });
});
