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

    const conversation = page.locator("main");

    // Put unique conversation content in the first campaign so we can later
    // prove that switching campaigns actually changes the visible content.
    await commandInput.fill("examine the lantern");
    const sendButton = page.getByRole("button", { name: "Send" });
    await expect(sendButton).toBeEnabled({ timeout: 20_000 });
    await sendButton.click();
    await expect(conversation.getByText("The narrator is responding...")).toHaveCount(0, {
      timeout: 20_000,
    });
    await expect(conversation.getByText("examine the lantern", { exact: true })).toBeVisible();

    // Create another campaign using the existing control.
    await page.getByRole("button", { name: "Create new campaign" }).first().click();
    await expect(sidebar.getByRole("button", { name: /^Delete session/ })).toHaveCount(2, {
      timeout: 20_000,
    });

    // The new campaign starts fresh and does not contain the first campaign's content.
    await expect(commandInput).toBeEnabled({ timeout: 20_000 });
    await expect(conversation.getByText("examine the lantern", { exact: true })).toHaveCount(0);

    const deleteButtons = sidebar.getByRole("button", { name: /^Delete session/ });

    // Switch back to the first campaign by clicking its session card and verify
    // its unique content reappears, proving the selection actually changed.
    const firstCampaignCard = sidebar.locator("button.w-full").nth(1);
    await firstCampaignCard.click();
    await expect(commandInput).toBeEnabled({ timeout: 20_000 });
    await expect(conversation.getByText("examine the lantern", { exact: true })).toBeVisible({
      timeout: 20_000,
    });

    // Delete a campaign and verify it is removed. The app uses window.confirm(); accept it.
    page.once("dialog", (dialog) => dialog.accept());
    await deleteButtons.first().click();
    await expect(sidebar.getByRole("button", { name: /^Delete session/ })).toHaveCount(1, {
      timeout: 20_000,
    });
  });
});
