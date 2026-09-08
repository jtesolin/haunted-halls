import { expect, test } from "@playwright/test";
import { resetE2ECampaigns } from "../support/campaigns";

test.describe("full chat round trip", () => {
  test.beforeEach(async ({ request, baseURL }) => {
    await resetE2ECampaigns(request, baseURL ?? "http://localhost:3000");
  });

  test("submits a deterministic command and renders the engine stub reply", async ({ page }) => {
    await page.goto("/");

    const commandInput = page.getByLabel("Enter your command");
    await expect(commandInput).toBeEnabled({ timeout: 20_000 });

    await commandInput.fill("look around");
    const sendButton = page.getByRole("button", { name: "Send" });
    await expect(sendButton).toBeEnabled({ timeout: 20_000 });
    await sendButton.click();

    const conversation = page.locator("main");

    // Optimistic player message is rendered immediately.
    await expect(conversation.getByText("look around", { exact: true })).toBeVisible();

    // Loading feedback is visible while the narrator reply is in flight.
    await expect(conversation.getByText("The narrator is responding...")).toBeVisible();

    // The engine stub reply returns through the BFF and is rendered; loading
    // feedback disappears once the turn completes.
    await expect(conversation.getByText("The narrator is responding...")).toHaveCount(0, {
      timeout: 20_000,
    });

    // The command input becomes enabled again and regains focus so the next
    // command can be typed without an extra click.
    await expect(commandInput).toBeEnabled();
    await expect(commandInput).toBeFocused();
    await expect(commandInput).toHaveValue("");
  });
});
