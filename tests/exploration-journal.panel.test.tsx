import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ExplorationJournalPanel from "@/components/ExplorationJournalPanel";

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

const GRAPH = {
  current_location: { id: "hall", name: "Great Hall" },
  nodes: [
    { id: "hall", kind: "room", name: "Great Hall" },
    { id: "library", kind: "room", name: "Library" },
    { id: "frontier-abc", kind: "frontier", name: null },
  ],
  edges: [
    { id: "hall/exit/n", source: "hall", target: "library", kind: "exit", label: "north door", traversed: true },
    { id: "hall/exit/e", source: "hall", target: "frontier-abc", kind: "exit", label: "east door", traversed: false },
    { id: "library/exit/s", source: "library", target: "hall", kind: "exit", label: "south door", traversed: true },
  ],
  observations: ["A cold hearth.", "The cellar door is locked."],
};
const LIBRARY_NOTES = { room: { id: "library", name: "Library" }, current: false, notes: ["Caretaker was here."] };

function mockApi(overrides: Partial<Record<"graph" | "room", () => Promise<Response>>> = {}) {
  global.fetch = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/exploration/rooms/")) {
      return (overrides.room ?? (() => json(LIBRARY_NOTES)))();
    }
    return (overrides.graph ?? (() => json(GRAPH)))();
  }) as unknown as typeof fetch;
}

function renderPanel(props: Partial<React.ComponentProps<typeof ExplorationJournalPanel>> = {}) {
  return render(
    <ExplorationJournalPanel
      campaignId="c1"
      refreshKey={0}
      closeLabel="Collapse sidebar"
      onClose={vi.fn()}
      {...props}
    />
  );
}

describe("ExplorationJournalPanel", () => {
  beforeEach(() => {
    mockApi();
  });

  it("shows loading, then the map above the journal entry for the current room", async () => {
    renderPanel();
    expect(screen.getByText("Loading exploration journal...")).toBeInTheDocument();

    expect(await screen.findByText("A cold hearth.")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith("/api/campaign/c1/exploration", expect.objectContaining({ cache: "no-store" }));
    const headings = screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent);
    expect(headings).toEqual(["Exploration Map", "Journal Entry"]);
    expect(screen.getByText("The cellar door is locked.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Return to Current Room" })).not.toBeInTheDocument();
    const current = screen.getByRole("button", { name: "Great Hall (current room)" });
    expect(current).toHaveAttribute("aria-pressed", "true");
  });

  it("selecting a visited room loads its persisted notes and return-to-current restores the live room", async () => {
    renderPanel();
    await screen.findByText("A cold hearth.");

    fireEvent.click(screen.getByRole("button", { name: "Library" }));

    expect(await screen.findByText("Caretaker was here.")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/campaign/c1/exploration/rooms/library",
      expect.objectContaining({ cache: "no-store" })
    );
    expect(screen.queryByText("A cold hearth.")).not.toBeInTheDocument();
    // Selected and current are distinguishable.
    expect(screen.getByRole("button", { name: "Library" })).toHaveAttribute("data-selected", "true");
    expect(screen.getByRole("button", { name: "Library" })).toHaveAttribute("data-current", "false");
    expect(screen.getByRole("button", { name: "Great Hall (current room)" })).toHaveAttribute("data-selected", "false");
    expect(screen.getByRole("button", { name: "Great Hall (current room)" })).toHaveAttribute("data-current", "true");

    fireEvent.click(screen.getByRole("button", { name: "Return to Current Room" }));
    expect(await screen.findByText("A cold hearth.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Return to Current Room" })).not.toBeInTheDocument();
  });

  it("supports keyboard selection of a visited room", async () => {
    renderPanel();
    await screen.findByText("A cold hearth.");

    fireEvent.keyDown(screen.getByRole("button", { name: "Library" }), { key: "Enter" });

    expect(await screen.findByText("Caretaker was here.")).toBeInTheDocument();
  });

  it("keeps unknown frontiers anonymous and non-selectable", async () => {
    renderPanel();
    await screen.findByText("A cold hearth.");
    const callsBefore = vi.mocked(global.fetch).mock.calls.length;

    const frontier = screen.getByTestId("map-frontier");
    expect(frontier).toHaveTextContent("?");
    expect(frontier).not.toHaveAttribute("role");
    expect(frontier.textContent).not.toContain("frontier-abc");
    fireEvent.click(frontier);

    expect(vi.mocked(global.fetch).mock.calls).toHaveLength(callsBefore);
    expect(screen.queryByRole("button", { name: /frontier|unexplored/i })).not.toBeInTheDocument();
    expect(screen.getByText("A cold hearth.")).toBeInTheDocument();
  });

  it("collapses and expands the map and journal independently, and reopens the journal on selection", async () => {
    renderPanel();
    await screen.findByText("A cold hearth.");
    const mapToggle = screen.getByRole("button", { name: "Exploration Map" });
    const journalToggle = screen.getByRole("button", { name: "Journal Entry" });
    expect(mapToggle).toHaveAttribute("aria-expanded", "true");
    expect(journalToggle).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(mapToggle);
    expect(mapToggle).toHaveAttribute("aria-expanded", "false");
    expect(journalToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("A cold hearth.")).toBeVisible();

    fireEvent.click(mapToggle);
    fireEvent.click(journalToggle);
    expect(journalToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "Library" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    expect(journalToggle).toHaveAttribute("aria-expanded", "true");
  });

  it("shows an error with retry when the graph fails, then recovers", async () => {
    let fail = true;
    mockApi({ graph: () => (fail ? json({ detail: "boom" }, 500) : json(GRAPH)) });
    renderPanel();

    expect(await screen.findByText("The exploration journal could not be loaded.")).toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("A cold hearth.")).toBeInTheDocument();
  });

  it("maps a 401 to a sign-in message", async () => {
    mockApi({ graph: () => json({}, 401) });
    renderPanel();
    expect(await screen.findByText("Sign in again to view the exploration journal.")).toBeInTheDocument();
  });

  it("shows an empty state when the campaign has no exploration state yet (404)", async () => {
    mockApi({ graph: () => json({ detail: "Campaign not found" }, 404) });
    renderPanel();
    expect(await screen.findByText(/Nothing explored yet/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3 })).not.toBeInTheDocument();
  });

  it("rejects a malformed graph payload instead of rendering it", async () => {
    mockApi({ graph: () => json({ current_location: { id: "x" } }) });
    renderPanel();
    expect(await screen.findByText("The exploration journal could not be loaded.")).toBeInTheDocument();
  });

  it("shows an empty-notes state for a room with no observations", async () => {
    mockApi({ graph: () => json({ ...GRAPH, observations: [] }) });
    renderPanel();
    expect(await screen.findByText("Nothing noteworthy recorded for this room yet.")).toBeInTheDocument();
  });

  it("shows loading, error and retry states for historical room notes", async () => {
    let fail = true;
    let release: (response: Response) => void = () => {};
    mockApi({
      room: () =>
        fail
          ? new Promise<Response>((resolve) => {
              release = resolve;
            })
          : json(LIBRARY_NOTES),
    });
    renderPanel();
    await screen.findByText("A cold hearth.");

    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    expect(screen.getByText("Loading notes...")).toBeInTheDocument();
    await act(async () => release(new Response("{}", { status: 404 })));
    expect(await screen.findByText("No notes are available for this room.")).toBeInTheDocument();
    // Never falls back to current-room observations for a different room.
    expect(screen.queryByText("A cold hearth.")).not.toBeInTheDocument();

    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Caretaker was here.")).toBeInTheDocument();
  });

  it("refetches when refreshKey changes and follows the current room, but keeps a chosen historical room", async () => {
    const view = renderPanel();
    await screen.findByText("A cold hearth.");

    const moved = {
      ...GRAPH,
      current_location: { id: "library", name: "Library" },
      observations: ["Dusty shelves."],
    };
    mockApi({ graph: () => json(moved) });
    view.rerender(
      <ExplorationJournalPanel campaignId="c1" refreshKey={1} closeLabel="x" onClose={vi.fn()} />
    );
    expect(await screen.findByText("Dusty shelves.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Library (current room)" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Great Hall" }));
    mockApi({
      graph: () => json(moved),
      room: () => json({ room: { id: "hall", name: "Great Hall" }, current: false, notes: ["Hearth gone cold."] }),
    });
    view.rerender(
      <ExplorationJournalPanel campaignId="c1" refreshKey={2} closeLabel="x" onClose={vi.fn()} />
    );
    expect(await screen.findByText("Hearth gone cold.")).toBeInTheDocument();
  });

  it("zoom controls and close button work", async () => {
    const onClose = vi.fn();
    renderPanel({ onClose });
    await screen.findByText("A cold hearth.");
    const group = screen.getByRole("group", { name: "Map zoom" });
    fireEvent.click(within(group).getByRole("button", { name: "Zoom in" }));
    fireEvent.click(within(group).getByRole("button", { name: "Zoom out" }));
    fireEvent.click(within(group).getByRole("button", { name: "Reset map view" }));
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
