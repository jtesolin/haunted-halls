import { expect, test } from "@playwright/test";
import { resetE2ECampaigns } from "../support/campaigns";

test.describe("campaign lifecycle", () => {
  test.beforeEach(async ({ request, baseURL }) => {
    await resetE2ECampaigns(request, baseURL ?? "http://localhost:3000");
  });

  test("creates, switches, and deletes a campaign through the real backend", async ({ page }) => {
    await page.goto("/");

    const commandInput = page.getByLabel("Enter your command");
    await expect(commandInput).toBeEnabled({ timeout: 20_000 });

    const sidebar = page.locator("#campaign-sidebar");
    await expect(sidebar.getByRole("button", { name: /^Delete session/ })).toHaveCount(1, {
      timeout: 20_000,
    });

    // Create another campaign using the existing control.
    await page.getByRole("button", { name: "Create new campaign" }).first().click();
    await expect(sidebar.getByRole("button", { name: /^Delete session/ })).toHaveCount(2, {
      timeout: 20_000,
    });

    const deleteButtons = sidebar.getByRole("button", { name: /^Delete session/ });

    // Switch to the other campaign by clicking its session card.
    const secondCampaignCard = sidebar.locator("button.w-full").nth(1);
    await secondCampaignCard.click();
    await expect(commandInput).toBeEnabled({ timeout: 20_000 });

    // Delete a campaign and verify it is removed. The app uses window.confirm(); accept it.
    page.once("dialog", (dialog) => dialog.accept());
    await deleteButtons.first().click();
    await expect(sidebar.getByRole("button", { name: /^Delete session/ })).toHaveCount(1, {
      timeout: 20_000,
    });
  });
});
