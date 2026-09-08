import { expect, test } from "@playwright/test";
import { resetE2ECampaigns } from "../support/campaigns";

test.describe("persistence across reload", () => {
  test.beforeEach(async ({ request, baseURL }) => {
    await resetE2ECampaigns(request, baseURL ?? "http://localhost:3000");
  });

  test("reloads the existing campaign from PostgreSQL with prior messages intact", async ({ page }) => {
    await page.goto("/");

    const commandInput = page.getByLabel("Enter your command");
    await expect(commandInput).toBeEnabled({ timeout: 20_000 });

    await commandInput.fill("look around");
    const sendButton = page.getByRole("button", { name: "Send" });
    await expect(sendButton).toBeEnabled({ timeout: 20_000 });
    await sendButton.click();

    const conversation = page.locator("main");
    await expect(conversation.getByText("The narrator is responding...")).toHaveCount(0, {
      timeout: 20_000,
    });

    await expect(conversation.getByText("look around", { exact: true })).toBeVisible();
    await expect(conversation.getByText("AI narrator replies (stub): look around")).toBeVisible();

    await page.reload();

    // The existing campaign (and its prior turn) is loaded from PostgreSQL through
    // the normal campaign APIs, not recreated from scratch.
    await expect(page.getByLabel("Enter your command")).toBeEnabled({ timeout: 20_000 });
    await expect(page.locator("main").getByText("look around", { exact: true })).toBeVisible({
      timeout: 20_000,
    });
    await expect(
      page.locator("main").getByText("AI narrator replies (stub): look around"),
    ).toBeVisible({ timeout: 20_000 });
  });
});
