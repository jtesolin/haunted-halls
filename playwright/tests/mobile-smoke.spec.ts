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

    const openSidebarButton = page.getByRole("button", { name: "Open sidebar" });
    await expect(openSidebarButton).toBeVisible();

    await openSidebarButton.click();
    const sidebar = page.locator("#campaign-sidebar");
    await expect(sidebar).toBeVisible();
    const closeSidebarButton = page.getByRole("button", { name: "Close sidebar", exact: true });
    await expect(closeSidebarButton).toBeVisible();

    await closeSidebarButton.click();
    await expect(openSidebarButton).toBeVisible();

    const bodyOverflow = await page.evaluate(() => {
      return document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1;
    });
    expect(bodyOverflow).toBe(true);
  });
});
