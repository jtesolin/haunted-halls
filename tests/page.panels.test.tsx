import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Home from "@/app/page";
import { useSession } from "next-auth/react";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(),
  signIn: vi.fn(),
  getProviders: vi.fn().mockResolvedValue({}),
  signOut: vi.fn(),
  SessionProvider: ({ children }: { children: ReactNode }) => children,
}));

const CHARACTER = {
  character_id: "char-1",
  name: "Ada Vale",
  inventory: [{ id: "lantern", name: "Brass Lantern", description: "Lights the dark.", quantity: 1 }],
  abilities: [{ ability_id: "a1", display_name: "Lockpicking", description: "Open locks.", available: true }],
};

type Campaigns = { campaign_id: string; name: string; last_message: string | null; character_id: string | null }[];

function mockBackend(campaigns: Campaigns) {
  const characterFetches: string[] = [];
  global.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/campaign" && init?.method === "POST") {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            campaign_id: "c-new",
            name: "Fresh start",
            description: null,
            truncated: false,
            character_id: null,
            messages: [{ turn_id: "t-new", role: "assistant", content: "A blank page", created_at: "2026-01-02" }],
          }),
          { status: 201 }
        )
      );
    }
    if (url === "/api/campaigns") {
      return Promise.resolve(new Response(JSON.stringify(campaigns), { status: 200 }));
    }
    if (url.startsWith("/api/campaign/")) {
      const id = decodeURIComponent(url.split("/").pop()!);
      const campaign = campaigns.find((entry) => entry.campaign_id === id)!;
      return Promise.resolve(
        new Response(
          JSON.stringify({
            ...campaign,
            description: null,
            truncated: false,
            messages: [{ turn_id: `t-${id}`, role: "assistant", content: `Welcome to ${campaign.name}`, created_at: "2026-01-01" }],
          }),
          { status: 200 }
        )
      );
    }
    if (url.startsWith("/api/character/")) {
      characterFetches.push(url);
      return Promise.resolve(new Response(JSON.stringify(CHARACTER), { status: 200 }));
    }
    return Promise.resolve(new Response("{}", { status: 200 }));
  }) as unknown as typeof fetch;
  return { characterFetches };
}

function setMobile(isMobile: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: isMobile,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

const WITH_CHARACTER: Campaigns = [{ campaign_id: "c1", name: "Crypt", last_message: "hi", character_id: "char-1" }];

describe("unified sidebar panel navigation", () => {
  beforeEach(() => {
    vi.mocked(useSession).mockReturnValue({
      data: { user: { name: "P", email: "p@example.com", image: null }, expires: "2099-01-01T00:00:00.000Z" },
      status: "authenticated",
      update: vi.fn(),
    });
    window.localStorage.clear();
    window.history.replaceState({}, "", "/");
  });

  describe("desktop", () => {
    beforeEach(() => setMobile(false));

    it("opens Campaigns by default with distinct, labelled rail buttons", async () => {
      mockBackend(WITH_CHARACTER);
      render(<Home />);

      const campaignsButton = screen.getByRole("button", { name: "Campaigns" });
      const characterButton = await screen.findByRole("button", { name: "Character Sheet" });
      expect(campaignsButton).toHaveAttribute("aria-expanded", "true");
      expect(campaignsButton).toHaveAttribute("title", "Campaigns");
      expect(characterButton).toHaveAttribute("aria-expanded", "false");
      expect(document.getElementById("campaign-sidebar")).toBeInTheDocument();
      expect(document.getElementById("character-sheet-panel")).not.toBeInTheDocument();
    });

    it("keeps the two panels mutually exclusive and toggles the active panel closed", async () => {
      mockBackend(WITH_CHARACTER);
      render(<Home />);
      await screen.findByText("Welcome to Crypt");
      const characterButton = screen.getByRole("button", { name: "Character Sheet" });
      await waitFor(() => expect(characterButton).toBeEnabled());

      fireEvent.click(characterButton);
      expect(await screen.findByText("Ada Vale")).toBeInTheDocument();
      expect(document.getElementById("campaign-sidebar")).not.toBeInTheDocument();
      expect(characterButton).toHaveAttribute("aria-expanded", "true");
      expect(screen.getByRole("button", { name: "Campaigns" })).toHaveAttribute("aria-expanded", "false");

      fireEvent.click(screen.getByRole("button", { name: "Campaigns" }));
      expect(document.getElementById("campaign-sidebar")).toBeInTheDocument();
      expect(document.getElementById("character-sheet-panel")).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "Campaigns" }));
      expect(document.getElementById("campaign-sidebar")).not.toBeInTheDocument();
      expect(document.getElementById("character-sheet-panel")).not.toBeInTheDocument();
      expect(window.localStorage.getItem("haunted-halls-sidebar-collapsed")).toBe("true");
      // The conversation stays visible while panels change.
      expect(screen.getByText("Welcome to Crypt")).toBeInTheDocument();
    });

    it("refreshes character details every time the panel opens", async () => {
      const { characterFetches } = mockBackend(WITH_CHARACTER);
      render(<Home />);
      await screen.findByText("Welcome to Crypt");
      const characterButton = screen.getByRole("button", { name: "Character Sheet" });
      await waitFor(() => expect(characterButton).toBeEnabled());

      fireEvent.click(characterButton);
      await screen.findByText("Ada Vale");
      fireEvent.click(characterButton);
      fireEvent.click(characterButton);
      await screen.findByText("Ada Vale");
      expect(characterFetches).toEqual(["/api/character/char-1", "/api/character/char-1"]);
    });

    it("disables the Character entry when the campaign has no character", async () => {
      mockBackend([{ campaign_id: "c1", name: "Crypt", last_message: "hi", character_id: null }]);
      render(<Home />);
      await screen.findByText("Welcome to Crypt");

      const characterButton = screen.getByRole("button", { name: "Character Sheet" });
      expect(characterButton).toBeDisabled();
      expect(characterButton).toHaveAttribute("title", expect.stringMatching(/available once/));
    });

    it("preserves the unsent draft and selected campaign while switching panels", async () => {
      mockBackend([
        { campaign_id: "c1", name: "Crypt", last_message: "hi", character_id: "char-1" },
        { campaign_id: "c2", name: "Tower", last_message: "yo", character_id: "char-2" },
      ]);
      render(<Home />);
      await screen.findByText("Welcome to Crypt");

      fireEvent.click(screen.getByRole("button", { name: /^Tower/ }));
      await screen.findByText("Welcome to Tower");
      const input = screen.getByRole("textbox", { name: "Enter your command" });
      fireEvent.change(input, { value: "open the door", target: { value: "open the door" } });
      const campaignFetchesBefore = vi.mocked(global.fetch).mock.calls.filter(([url]) =>
        String(url).startsWith("/api/campaign/")
      ).length;

      fireEvent.click(screen.getByRole("button", { name: "Character Sheet" }));
      await screen.findByText("Ada Vale");
      fireEvent.click(screen.getByRole("button", { name: "Campaigns" }));

      expect(screen.getByRole("textbox", { name: "Enter your command" })).toHaveValue("open the door");
      expect(screen.getByText("Welcome to Tower")).toBeInTheDocument();
      expect(screen.queryByText("Welcome to Crypt")).not.toBeInTheDocument();
      expect(
        vi.mocked(global.fetch).mock.calls.filter(([url]) => String(url).startsWith("/api/campaign/")).length
      ).toBe(campaignFetchesBefore);
      // The character panel fetched the selected campaign's character, not another one.
      expect(
        vi.mocked(global.fetch).mock.calls.some(([url]) => String(url) === "/api/character/char-2")
      ).toBe(true);
    });
  });

  describe("desktop panel state edge cases", () => {
    beforeEach(() => setMobile(false));

    it("keeps the Character panel usable when the active campaign changes to one without a character", async () => {
      mockBackend(WITH_CHARACTER);
      render(<Home />);
      await screen.findByText("Welcome to Crypt");
      const characterButton = screen.getByRole("button", { name: "Character Sheet" });
      await waitFor(() => expect(characterButton).toBeEnabled());
      fireEvent.click(characterButton);
      await screen.findByText("Ada Vale");

      // Creating a campaign from the rail activates a campaign whose character_id is null.
      fireEvent.click(screen.getByRole("button", { name: "Create new campaign" }));
      await screen.findByText("A blank page");

      expect(screen.queryByText("Ada Vale")).not.toBeInTheDocument();
      expect(screen.getByText(/No character is available for this campaign yet/)).toBeInTheDocument();
      // The open panel can still be closed because its button stays enabled.
      const openCharacterButton = screen.getByRole("button", { name: "Character Sheet" });
      expect(openCharacterButton).toBeEnabled();
      fireEvent.click(openCharacterButton);
      expect(document.getElementById("character-sheet-panel")).not.toBeInTheDocument();
      // Once closed, the entry is disabled for the character-less campaign.
      expect(screen.getByRole("button", { name: "Character Sheet" })).toBeDisabled();
    });

    it("restores a saved collapsed rail preference on load", async () => {
      window.localStorage.setItem("haunted-halls-sidebar-collapsed", "true");
      mockBackend(WITH_CHARACTER);
      render(<Home />);

      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Campaigns" })).toHaveAttribute("aria-expanded", "false")
      );
      expect(document.getElementById("campaign-sidebar")).not.toBeInTheDocument();
      expect(await screen.findByText("Welcome to Crypt")).toBeInTheDocument();
    });

    it("keeps Campaigns open for an explicit expanded or unrecognized saved preference", async () => {
      window.localStorage.setItem("haunted-halls-sidebar-collapsed", "false");
      mockBackend(WITH_CHARACTER);
      const { unmount } = render(<Home />);
      await screen.findByText("Welcome to Crypt");
      expect(screen.getByRole("button", { name: "Campaigns" })).toHaveAttribute("aria-expanded", "true");
      unmount();

      window.localStorage.setItem("haunted-halls-sidebar-collapsed", "garbage");
      mockBackend(WITH_CHARACTER);
      render(<Home />);
      await screen.findByText("Welcome to Crypt");
      expect(screen.getByRole("button", { name: "Campaigns" })).toHaveAttribute("aria-expanded", "true");
    });
  });

  describe("mobile", () => {
    beforeEach(() => setMobile(true));

    it("hamburger -> menu -> panel -> Back to Conversation, with focus handling", async () => {
      mockBackend(WITH_CHARACTER);
      render(<Home />);
      await screen.findByText("Welcome to Crypt");

      // No stacked panels/overlays and no desktop rail on mobile.
      expect(document.getElementById("campaign-sidebar")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Campaigns" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Open sidebar" })).not.toBeInTheDocument();

      const hamburger = screen.getByRole("button", { name: "Open navigation menu" });
      await waitFor(() => expect(hamburger).toBeEnabled());
      fireEvent.click(hamburger);

      const menu = screen.getByRole("dialog", { name: "Navigation menu" });
      expect(hamburger).toHaveAttribute("aria-expanded", "true");
      expect(within(menu).getByRole("button", { name: "Campaigns" })).toHaveFocus();
      expect(within(menu).getByRole("button", { name: "Character Sheet" })).toBeEnabled();

      fireEvent.click(within(menu).getByRole("button", { name: "Character Sheet" }));
      expect(screen.queryByRole("dialog", { name: "Navigation menu" })).not.toBeInTheDocument();
      expect(await screen.findByText("Ada Vale")).toBeInTheDocument();
      expect(document.getElementById("campaign-sidebar")).not.toBeInTheDocument();
      const back = screen.getByRole("button", { name: "Back to Conversation" });
      expect(back).toHaveFocus();

      fireEvent.click(back);
      expect(document.getElementById("character-sheet-panel")).not.toBeInTheDocument();
      expect(screen.getByText("Welcome to Crypt")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Open navigation menu" })).toHaveFocus();
    });

    it("opens Campaigns from the menu and closes on Escape", async () => {
      mockBackend(WITH_CHARACTER);
      render(<Home />);
      await screen.findByText("Welcome to Crypt");

      fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
      fireEvent.click(screen.getByRole("button", { name: "Campaigns" }));
      expect(document.getElementById("campaign-sidebar")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Back to Conversation" })).toHaveFocus();

      fireEvent.keyDown(window, { key: "Escape" });
      expect(document.getElementById("campaign-sidebar")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Open navigation menu" })).toHaveFocus();

      fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
      fireEvent.keyDown(window, { key: "Escape" });
      expect(screen.queryByRole("dialog", { name: "Navigation menu" })).not.toBeInTheDocument();
    });

    it("closes the Character panel on Escape and returns focus to the hamburger", async () => {
      mockBackend(WITH_CHARACTER);
      render(<Home />);
      await screen.findByText("Welcome to Crypt");

      fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
      fireEvent.click(screen.getByRole("button", { name: "Character Sheet" }));
      await screen.findByText("Ada Vale");

      fireEvent.keyDown(window, { key: "Escape" });
      expect(document.getElementById("character-sheet-panel")).not.toBeInTheDocument();
      expect(screen.getByText("Welcome to Crypt")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Open navigation menu" })).toHaveFocus();
    });

    it("selecting a campaign returns to the conversation, and the draft survives the round trip", async () => {
      mockBackend(WITH_CHARACTER);
      render(<Home />);
      await screen.findByText("Welcome to Crypt");
      fireEvent.change(screen.getByRole("textbox", { name: "Enter your command" }), {
        target: { value: "draft text" },
      });

      fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
      fireEvent.click(screen.getByRole("button", { name: "Back to Conversation" }));
      fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
      fireEvent.click(screen.getByRole("button", { name: "Character Sheet" }));
      await screen.findByText("Ada Vale");
      fireEvent.click(screen.getByRole("button", { name: "Back to Conversation" }));

      expect(screen.getByRole("textbox", { name: "Enter your command" })).toHaveValue("draft text");
    });

    it("disables the Character Sheet menu entry when there is no character", async () => {
      mockBackend([{ campaign_id: "c1", name: "Crypt", last_message: "hi", character_id: null }]);
      render(<Home />);
      await screen.findByText("Welcome to Crypt");

      fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
      expect(screen.getByRole("button", { name: "Character Sheet" })).toBeDisabled();
    });
  });
});
