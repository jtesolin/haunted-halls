import { expect, test } from "@playwright/test";

// Unauthenticated shell must never click through to any sign-in provider.
// It uses empty storage state, independent of the authenticated
// Chromium project's saved playwright/.auth/user.json.
test.use({ storageState: { cookies: [], origins: [] } });

test.describe("unauthenticated shell", () => {
  test("shows signed-out campaign prompt, mode-neutral sign-in control, and disabled command input", async ({
    page,
  }) => {
    await page.goto("/");

    await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
    await expect(page.getByText("Sign in to start or continue a campaign.")).toBeVisible();

    const commandInput = page.getByLabel("Enter your command");
    await expect(commandInput).toBeDisabled();
  });
});
