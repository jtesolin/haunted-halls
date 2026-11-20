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
    fireEvent.click(within(group).getByRole("button", { name: "Fit whole map" }));
    fireEvent.click(within(group).getByRole("button", { name: "Center on current room" }));
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("starts at a readable scale centred on the current room for a large graph", async () => {
    const nodes = Array.from({ length: 30 }, (_, i) => ({ id: `r${i}`, kind: "room", name: `Room ${i}` }));
    const edges = nodes.slice(1).map((node, i) => ({
      id: `e${i}`,
      source: nodes[i].id,
      target: node.id,
      kind: "exit",
      label: "on",
      traversed: true,
    }));
    mockApi({
      graph: () =>
        json({ current_location: { id: "r15", name: "Room 15" }, nodes, edges, observations: ["Mid corridor."] }),
    });
    renderPanel();
    await screen.findByText("Mid corridor.");

    const svg = screen.getByRole("group", { name: "Exploration map" });
    expect(svg).toHaveAttribute("data-view-scale", "1");
    const [vx, , vw] = svg.getAttribute("viewBox")!.split(" ").map(Number);
    // 1 map unit = 1 px at the default view (fallback width) and the current room (x=0 here) is inside it.
    expect(vw).toBeLessThan(400);
    expect(vx).toBeLessThan(0);
    expect(vx + vw).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: /^Room \d+/ })).toHaveLength(30);

    fireEvent.click(screen.getByRole("button", { name: "Fit whole map" }));
    expect(Number(svg.getAttribute("data-view-scale"))).toBeLessThan(1);
    fireEvent.click(screen.getByRole("button", { name: "Center on current room" }));
    expect(svg).toHaveAttribute("data-view-scale", "1");
  });

  it("zooms with ctrl+wheel but leaves plain wheel for scrolling the drawer", async () => {
    renderPanel();
    await screen.findByText("A cold hearth.");
    const svg = screen.getByRole("group", { name: "Exploration map" });

    fireEvent.wheel(svg, { deltaY: -100 });
    expect(svg).toHaveAttribute("data-view-scale", "1");
    fireEvent.wheel(svg, { deltaY: -100, ctrlKey: true });
    expect(Number(svg.getAttribute("data-view-scale"))).toBeGreaterThan(1);
  });

  it("follows the current room again after a picked room becomes current", async () => {
    const view = renderPanel();
    await screen.findByText("A cold hearth.");
    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    await screen.findByText("Caretaker was here.");

    const inLibrary = { ...GRAPH, current_location: { id: "library", name: "Library" }, observations: ["Dusty shelves."] };
    mockApi({ graph: () => json(inLibrary) });
    view.rerender(<ExplorationJournalPanel campaignId="c1" refreshKey={1} closeLabel="x" onClose={vi.fn()} />);
    expect(await screen.findByText("Dusty shelves.")).toBeInTheDocument();

    const inHall = { ...GRAPH, observations: ["Back by the hearth."] };
    mockApi({ graph: () => json(inHall) });
    view.rerender(<ExplorationJournalPanel campaignId="c1" refreshKey={2} closeLabel="x" onClose={vi.fn()} />);
    expect(await screen.findByText("Back by the hearth.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Return to Current Room" })).not.toBeInTheDocument();
  });

  it("keeps the last good graph and notes when a background refresh fails or is pending", async () => {
    const view = renderPanel();
    await screen.findByText("A cold hearth.");
    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    await screen.findByText("Caretaker was here.");

    let releaseGraph: (response: Response) => void = () => {};
    mockApi({
      graph: () => new Promise<Response>((resolve) => { releaseGraph = resolve; }),
      room: () => json({}, 500),
    });
    view.rerender(<ExplorationJournalPanel campaignId="c1" refreshKey={1} closeLabel="x" onClose={vi.fn()} />);
    // In flight: no spinner replaces what is shown.
    expect(screen.queryByText("Loading notes...")).not.toBeInTheDocument();
    expect(screen.queryByText("Loading exploration journal...")).not.toBeInTheDocument();
    expect(screen.getByText("Caretaker was here.")).toBeInTheDocument();

    await act(async () => releaseGraph(new Response("{}", { status: 500 })));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText("The exploration journal could not be loaded.")).not.toBeInTheDocument();
    expect(screen.queryByText("The room notes could not be loaded.")).not.toBeInTheDocument();
    expect(screen.getByText("Caretaker was here.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Library" })).toBeInTheDocument();
  });

  it("ignores a superseded graph response that resolves late", async () => {
    let releaseFirst: (response: Response) => void = () => {};
    let call = 0;
    mockApi({
      graph: () => {
        call += 1;
        return call === 1
          ? new Promise<Response>((resolve) => { releaseFirst = resolve; })
          : json({ ...GRAPH, observations: ["Fresh note."] });
      },
    });
    const view = renderPanel();
    view.rerender(<ExplorationJournalPanel campaignId="c1" refreshKey={1} closeLabel="x" onClose={vi.fn()} />);
    expect(await screen.findByText("Fresh note.")).toBeInTheDocument();

    await act(async () => releaseFirst(new Response(JSON.stringify({ ...GRAPH, observations: ["Stale note."] }))));
    expect(screen.queryByText("Stale note.")).not.toBeInTheDocument();
    expect(screen.getByText("Fresh note.")).toBeInTheDocument();
  });

  it("shows a close control and no fetches when there is no campaign", () => {
    const onClose = vi.fn();
    renderPanel({ campaignId: null, onClose });
    expect(screen.getByText("This campaign has not started yet.")).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("shows the error state for malformed nested graph and notes payloads instead of crashing", async () => {
    mockApi({ graph: () => json({ ...GRAPH, nodes: [null] }) });
    const first = renderPanel();
    expect(await screen.findByText("The exploration journal could not be loaded.")).toBeInTheDocument();
    first.unmount();

    mockApi({ room: () => json({ room: { id: "library", name: "Library" }, current: false, notes: [null] }) });
    renderPanel();
    await screen.findByText("A cold hearth.");
    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    expect(await screen.findByText("The room notes could not be loaded.")).toBeInTheDocument();
  });

  describe("map pointer handling", () => {
    const svg = () => screen.getByRole("group", { name: "Exploration map" });
    const center = () => {
      const [x, y, w, h] = svg().getAttribute("viewBox")!.split(" ").map(Number);
      return { x: x + w / 2, y: y + h / 2 };
    };
    const pointer = (type: string, init: Record<string, unknown>) =>
      fireEvent(svg(), Object.assign(new MouseEvent(type, { bubbles: true, ...init }), { pointerId: init.pointerId ?? 1, pointerType: init.pointerType ?? "mouse" }));

    it("drag pans the map and suppresses the click that follows", async () => {
      renderPanel();
      await screen.findByText("A cold hearth.");
      const before = center();

      pointer("pointerdown", { clientX: 100, clientY: 100, buttons: 1 });
      pointer("pointermove", { clientX: 160, clientY: 130, buttons: 1 });
      pointer("pointerup", { clientX: 160, clientY: 130 });
      expect(center().x).toBeLessThan(before.x);

      fireEvent.click(screen.getByRole("button", { name: "Library" }));
      expect(screen.queryByText("Caretaker was here.")).not.toBeInTheDocument();
    });

    it("a sub-threshold press still selects the room", async () => {
      renderPanel();
      await screen.findByText("A cold hearth.");
      const before = center();

      pointer("pointerdown", { clientX: 100, clientY: 100, buttons: 1 });
      pointer("pointermove", { clientX: 101, clientY: 101, buttons: 1 });
      pointer("pointerup", { clientX: 101, clientY: 101 });
      fireEvent.click(screen.getByRole("button", { name: "Library" }));

      expect(center()).toEqual(before);
      expect(await screen.findByText("Caretaker was here.")).toBeInTheDocument();
    });

    it("stops panning once the mouse button was released out of sight", async () => {
      renderPanel();
      await screen.findByText("A cold hearth.");
      pointer("pointerdown", { clientX: 100, clientY: 100, buttons: 1 });
      pointer("pointermove", { clientX: 140, clientY: 100, buttons: 1 });
      const panned = center();

      // Release happened outside: the next move over the map reports no button.
      pointer("pointermove", { clientX: 220, clientY: 100, buttons: 0 });

      expect(center()).toEqual(panned);
    });

    it("pinch changes the scale and lifting one finger does not make the map jump", async () => {
      renderPanel();
      await screen.findByText("A cold hearth.");
      pointer("pointerdown", { pointerId: 1, pointerType: "touch", clientX: 100, clientY: 100, buttons: 1 });
      pointer("pointerdown", { pointerId: 2, pointerType: "touch", clientX: 140, clientY: 100, buttons: 1 });
      pointer("pointermove", { pointerId: 2, pointerType: "touch", clientX: 220, clientY: 100, buttons: 1 });
      expect(Number(svg().getAttribute("data-view-scale"))).toBeGreaterThan(1);

      pointer("pointerup", { pointerId: 1, pointerType: "touch", clientX: 100, clientY: 100 });
      const settled = center();
      pointer("pointermove", { pointerId: 2, pointerType: "touch", clientX: 222, clientY: 100, buttons: 1 });

      expect(Math.abs(center().x - settled.x)).toBeLessThan(5);
    });

    it("re-homes the view when the current room changes, even after the user panned", async () => {
      const view = renderPanel();
      await screen.findByText("A cold hearth.");
      pointer("pointerdown", { clientX: 100, clientY: 100, buttons: 1 });
      pointer("pointermove", { clientX: 200, clientY: 100, buttons: 1 });
      pointer("pointerup", { clientX: 200, clientY: 100 });
      expect(center().x).not.toBe(0);

      mockApi({
        graph: () => json({ ...GRAPH, current_location: { id: "library", name: "Library" }, observations: ["Shelves."] }),
      });
      view.rerender(<ExplorationJournalPanel campaignId="c1" refreshKey={1} closeLabel="x" onClose={vi.fn()} />);
      await screen.findByText("Shelves.");

      expect(center()).toEqual({ x: 0, y: 0 });
    });

    it("mouse focus does not shift the view but keyboard focus does", async () => {
      const nodes = Array.from({ length: 8 }, (_, i) => ({ id: `r${i}`, kind: "room", name: `Room ${i}` }));
      const edges = nodes.slice(1).map((node, i) => ({
        id: `e${i}`, source: nodes[i].id, target: node.id, kind: "exit", label: "on", traversed: true,
      }));
      mockApi({ graph: () => json({ current_location: { id: "r0", name: "Room 0" }, nodes, edges, observations: ["x"] }) });
      renderPanel();
      await screen.findByText("x");
      const before = svg().getAttribute("viewBox");
      const node = screen.getByRole("button", { name: "Room 7" });

      const original = node.matches.bind(node);
      node.matches = (selector: string) => (selector === ":focus-visible" ? false : original(selector));
      fireEvent.focus(node);
      expect(svg().getAttribute("viewBox")).toBe(before);

      node.matches = (selector: string) => (selector === ":focus-visible" ? true : original(selector));
      fireEvent.focus(node);
      expect(svg().getAttribute("viewBox")).not.toBe(before);
    });
  });
});
