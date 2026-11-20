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

const GRAPH = {
  current_location: { id: "hall", name: "Great Hall" },
  nodes: [{ id: "hall", kind: "room", name: "Great Hall" }],
  edges: [],
  observations: ["A cold hearth."],
};

function mockBackend() {
  const explorationFetches: string[] = [];
  global.fetch = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/campaigns") {
      return Promise.resolve(
        new Response(JSON.stringify([{ campaign_id: "c1", name: "Crypt", last_message: "hi", character_id: "char-1" }]))
      );
    }
    if (url === "/api/chat") {
      return Promise.resolve(new Response(JSON.stringify({ reply: "You step into the hall.", campaign_id: "c1", turn_id: "t2" })));
    }
    if (url.endsWith("/exploration")) {
      explorationFetches.push(url);
      return Promise.resolve(new Response(JSON.stringify(GRAPH)));
    }
    if (url.startsWith("/api/campaign/")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            campaign_id: "c1",
            name: "Crypt",
            description: null,
            truncated: false,
            character_id: "char-1",
            messages: [{ turn_id: "t1", role: "assistant", content: "Welcome to Crypt", created_at: "2026-01-01" }],
          })
        )
      );
    }
    return Promise.resolve(new Response("{}"));
  }) as unknown as typeof fetch;
  return { explorationFetches };
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

describe("Exploration Journal navigation", () => {
  beforeEach(() => {
    vi.mocked(useSession).mockReturnValue({
      data: { user: { name: "P", email: "p@example.com", image: null }, expires: "2099-01-01T00:00:00.000Z" },
      status: "authenticated",
      update: vi.fn(),
    });
    window.localStorage.clear();
    window.history.replaceState({}, "", "/");
  });

  it("desktop: rail button opens the drawer, is exclusive with other panels, and toggles closed", async () => {
    setMobile(false);
    const { explorationFetches } = mockBackend();
    render(<Home />);
    await screen.findByText("Welcome to Crypt");

    const button = screen.getByRole("button", { name: "Exploration Journal" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);

    expect(await screen.findByText("A cold hearth.")).toBeInTheDocument();
    expect(explorationFetches).toEqual(["/api/campaign/c1/exploration"]);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(document.getElementById("campaign-sidebar")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Character Sheet" }));
    expect(document.getElementById("exploration-journal-panel")).not.toBeInTheDocument();

    fireEvent.click(button);
    fireEvent.click(button);
    expect(document.getElementById("exploration-journal-panel")).not.toBeInTheDocument();
    expect(screen.getByText("Welcome to Crypt")).toBeInTheDocument();
  });

  it("mobile: opens as a full-screen dialog from the menu and returns to the conversation", async () => {
    setMobile(true);
    mockBackend();
    render(<Home />);
    await screen.findByText("Welcome to Crypt");

    const hamburger = screen.getByRole("button", { name: "Open navigation menu" });
    await waitFor(() => expect(hamburger).toBeEnabled());
    fireEvent.click(hamburger);
    const menu = screen.getByRole("dialog", { name: "Navigation menu" });
    await waitFor(() => expect(within(menu).getByRole("button", { name: "Exploration Journal" })).toBeEnabled());
    fireEvent.click(within(menu).getByRole("button", { name: "Exploration Journal" }));

    expect(await screen.findByText("A cold hearth.")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Exploration Journal" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to Conversation" }));
    expect(document.getElementById("exploration-journal-panel")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open navigation menu" })).toHaveFocus();
  });

  it("refetches the journal after a turn completes", async () => {
    setMobile(false);
    const { explorationFetches } = mockBackend();
    render(<Home />);
    await screen.findByText("Welcome to Crypt");
    const button = screen.getByRole("button", { name: "Exploration Journal" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await screen.findByText("A cold hearth.");
    expect(explorationFetches).toHaveLength(1);

    fireEvent.change(screen.getByRole("textbox", { name: "Enter your command" }), { target: { value: "look" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await screen.findByText("You step into the hall.");
    await waitFor(() => expect(explorationFetches.length).toBeGreaterThan(1));
  });

  it("disables the entry for a campaign-less session", async () => {
    setMobile(false);
    global.fetch = vi.fn(() => Promise.resolve(new Response("[]"))) as unknown as typeof fetch;
    render(<Home />);
    expect(screen.getByRole("button", { name: "Exploration Journal" })).toBeDisabled();
  });
});
