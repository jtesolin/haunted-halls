import { expect, test } from "@playwright/test";
import { resetE2ECampaigns } from "../support/campaigns";

test.describe("authenticated session / initial campaign", () => {
  test.beforeEach(async ({ request, baseURL }) => {
    await resetE2ECampaigns(request, baseURL ?? "http://localhost:3000");
  });

  test("recognizes the signed-in session and creates/loads the opening campaign", async ({ page }) => {
    await page.goto("/");

    // Recognized as signed in through the normal NextAuth session (not a mock).
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    // With no existing campaigns for the E2E identity, the app's automatic
    // campaign-creation flow runs through the real BFF/engine/database path and the
    // deterministic opening narration is rendered as the first assistant message. The engine
    // grounds every opening with its campaign scenario hook (the deterministic fallback
    // scenario here, since the local provider returns no scenario) ahead of the narration.
    const commandInput = page.getByLabel("Enter your command");
    await expect(commandInput).toBeEnabled({ timeout: 20_000 });
    const openingMessage = page.locator("main").getByText(
      "A faded note asks you to return what the house took from someone, before the dark claims you both. " +
        "You stand in the Entry Hall. A lantern casts long shadows across the dusty floor. What do you do next?",
      { exact: true },
    );
    await expect(openingMessage).toBeVisible({ timeout: 20_000 });
  });
});
