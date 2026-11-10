import { expect, test } from "@playwright/test";
import { resetE2ECampaigns } from "../support/campaigns";

test.describe("mobile smoke test", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test.beforeEach(async ({ request, baseURL }) => {
    await resetE2ECampaigns(request, baseURL ?? "http://localhost:3000");
  });

  test("header, drawer, and layout remain usable at a mobile viewport", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    const menuButton = page.getByRole("button", { name: "Open navigation menu" });
    await expect(menuButton).toBeVisible();

    await menuButton.click();
    const menu = page.getByRole("dialog", { name: "Navigation menu" });
    await expect(menu).toBeVisible();
    // Keyboard focus stays inside the modal menu no matter how many times Tab is pressed.
    for (let index = 0; index < 5; index += 1) {
      await page.keyboard.press("Tab");
      await expect(menu.locator(":focus")).toHaveCount(1);
    }
    await page.getByRole("button", { name: "Campaigns" }).click();
    const sidebar = page.locator("#campaign-sidebar");
    await expect(sidebar).toBeVisible();
    const backButton = page.getByRole("button", { name: "Back to Conversation" });
    await expect(backButton).toBeVisible();

    await backButton.click();
    await expect(sidebar).toHaveCount(0);
    await expect(menuButton).toBeVisible();
    await expect(page.getByLabel("Enter your command")).toBeVisible();

    const bodyOverflow = await page.evaluate(() => {
      return document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1;
    });
    expect(bodyOverflow).toBe(true);
  });
});
