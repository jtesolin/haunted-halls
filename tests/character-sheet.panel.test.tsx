import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CharacterSheetPanel from "@/components/CharacterSheetPanel";

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

const CHARACTER = {
  character_id: "char-1",
  name: "Ada Vale",
  inventory: [
    { id: "lantern", name: "Brass Lantern", description: "Lights the dark.", quantity: 1 },
    { id: "coin", name: "Silver Coin", description: "Old currency.", quantity: 3 },
  ],
  abilities: [
    { ability_id: "a1", display_name: "Lockpicking", description: "Open simple locks.", available: true },
    {
      ability_id: "a2",
      display_name: "Shadow Step",
      description: "Slip unseen.",
      available: false,
      availability_reason: "Needs darkness",
    },
  ],
};

describe("CharacterSheetPanel", () => {
  beforeEach(() => {
    global.fetch = vi.fn() as unknown as typeof fetch;
  });

  it("shows name, abilities and inventory rows from the API field names", async () => {
    vi.mocked(global.fetch).mockImplementation(() => jsonResponse(CHARACTER));
    render(<CharacterSheetPanel characterId="char-1" closeLabel="Collapse sidebar" onClose={vi.fn()} />);

    expect(screen.getByText("Loading character...")).toBeInTheDocument();
    expect(await screen.findByText("Ada Vale")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/character/char-1",
      expect.objectContaining({ cache: "no-store" })
    );
    expect(screen.getByRole("heading", { name: "Character Sheet" })).toBeInTheDocument();
    expect(screen.getByText("Lockpicking")).toBeInTheDocument();
    expect(screen.getByText("Open simple locks.")).toBeInTheDocument();
    expect(screen.getByText("Unavailable: Needs darkness")).toBeInTheDocument();
    expect(screen.getByText("Brass Lantern")).toBeInTheDocument();
    expect(screen.getByText("×3")).toBeInTheDocument();
    // No unsupported stubbed properties.
    for (const label of [/health/i, /\bxp\b/i, /level/i, /class/i, /equipment/i]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: /equip|use|edit/i })).not.toBeInTheDocument();
  });

  it("collapses and expands the Abilities and Inventory sections", async () => {
    vi.mocked(global.fetch).mockImplementation(() => jsonResponse(CHARACTER));
    render(<CharacterSheetPanel characterId="char-1" closeLabel="Collapse sidebar" onClose={vi.fn()} />);
    await screen.findByText("Ada Vale");

    const abilitiesToggle = screen.getByRole("button", { name: /Abilities/ });
    expect(abilitiesToggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(abilitiesToggle);
    expect(abilitiesToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Lockpicking")).not.toBeVisible();
    expect(screen.getByText("Brass Lantern")).toBeVisible();

    fireEvent.click(abilitiesToggle);
    expect(screen.getByText("Lockpicking")).toBeVisible();

    const inventoryToggle = screen.getByRole("button", { name: /Inventory/ });
    fireEvent.click(inventoryToggle);
    expect(inventoryToggle).toHaveAttribute("aria-expanded", "false");
  });

  it("renders helpful empty states for empty abilities and inventory", async () => {
    vi.mocked(global.fetch).mockImplementation(() =>
      jsonResponse({ character_id: "char-1", name: "Ada Vale", inventory: [], abilities: [] })
    );
    render(<CharacterSheetPanel characterId="char-1" closeLabel="Collapse sidebar" onClose={vi.fn()} />);

    expect(await screen.findByText("No abilities yet.")).toBeInTheDocument();
    expect(screen.getByText("Your inventory is empty.")).toBeInTheDocument();
  });

  it("shows an empty state without fetching when no character is available", () => {
    render(<CharacterSheetPanel characterId={null} closeLabel="Collapse sidebar" onClose={vi.fn()} />);

    expect(screen.getByText(/No character is available for this campaign yet/)).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("shows an error with retry that refetches", async () => {
    vi.mocked(global.fetch)
      .mockImplementationOnce(() => jsonResponse({ error: "boom" }, 502))
      .mockImplementation(() => jsonResponse(CHARACTER));
    render(<CharacterSheetPanel characterId="char-1" closeLabel="Collapse sidebar" onClose={vi.fn()} />);

    expect(await screen.findByText("The character sheet could not be loaded.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Ada Vale")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it("maps 404 and network failures to distinct messages", async () => {
    vi.mocked(global.fetch).mockImplementationOnce(() => jsonResponse({ error: "nope" }, 404));
    const { unmount } = render(
      <CharacterSheetPanel characterId="char-1" closeLabel="Collapse sidebar" onClose={vi.fn()} />
    );
    expect(await screen.findByText("This character could not be found.")).toBeInTheDocument();
    unmount();

    vi.mocked(global.fetch).mockImplementationOnce(() => Promise.reject(new TypeError("offline")));
    render(<CharacterSheetPanel characterId="char-1" closeLabel="Collapse sidebar" onClose={vi.fn()} />);
    expect(await screen.findByText("The character sheet could not be loaded.")).toBeInTheDocument();
  });

  it("treats a malformed response as an error and tolerates missing arrays", async () => {
    vi.mocked(global.fetch).mockImplementationOnce(() => jsonResponse({ unexpected: true }));
    const { unmount } = render(
      <CharacterSheetPanel characterId="char-1" closeLabel="Collapse sidebar" onClose={vi.fn()} />
    );
    expect(await screen.findByText("The character sheet could not be loaded.")).toBeInTheDocument();
    unmount();

    vi.mocked(global.fetch).mockImplementationOnce(() => jsonResponse({ character_id: "char-1", name: "Ada Vale" }));
    render(<CharacterSheetPanel characterId="char-1" closeLabel="Collapse sidebar" onClose={vi.fn()} />);
    expect(await screen.findByText("No abilities yet.")).toBeInTheDocument();
  });

  it("refetches when the character changes and ignores superseded responses", async () => {
    let resolveFirst: (response: Response) => void = () => {};
    vi.mocked(global.fetch)
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveFirst = resolve;
          })
      )
      .mockImplementation(() => jsonResponse({ ...CHARACTER, character_id: "char-2", name: "Bram" }));

    const { rerender } = render(
      <CharacterSheetPanel characterId="char-1" closeLabel="Collapse sidebar" onClose={vi.fn()} />
    );
    rerender(<CharacterSheetPanel characterId="char-2" closeLabel="Collapse sidebar" onClose={vi.fn()} />);
    expect(await screen.findByText("Bram")).toBeInTheDocument();

    resolveFirst(new Response(JSON.stringify(CHARACTER), { status: 200 }));
    await waitFor(() => expect(screen.getByText("Bram")).toBeInTheDocument());
    expect(screen.queryByText("Ada Vale")).not.toBeInTheDocument();
  });

  it("calls onClose from the labelled close control", async () => {
    vi.mocked(global.fetch).mockImplementation(() => jsonResponse(CHARACTER));
    const onClose = vi.fn();
    render(
      <CharacterSheetPanel
        characterId="char-1"
        closeLabel="Back to Conversation"
        closeText="Back"
        onClose={onClose}
      />
    );
    await screen.findByText("Ada Vale");
    const panel = screen.getByRole("heading", { name: "Character Sheet" }).closest("div")!.parentElement!;
    fireEvent.click(within(panel).getByRole("button", { name: "Back to Conversation" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
