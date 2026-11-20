import { describe, expect, it } from "vitest";
import { layoutGraph } from "@/lib/exploration-layout";
import type { ExplorationEdge, ExplorationNode } from "@/types/exploration";

const room = (id: string): ExplorationNode => ({ id, kind: "room", name: id });
const edge = (id: string, source: string, target: string): ExplorationEdge => ({
  id,
  source,
  target,
  kind: "exit",
  label: id,
  traversed: true,
});

describe("layoutGraph", () => {
  it("places every node once without overlap, including cycles and disconnected rooms", () => {
    const nodes = [room("a"), room("b"), room("c"), room("lone"), { id: "frontier-1", kind: "frontier" } as ExplorationNode];
    const edges = [edge("ab", "a", "b"), edge("bc", "b", "c"), edge("ca", "c", "a"), edge("af", "a", "frontier-1")];
    const layout = layoutGraph(nodes, edges, "a");

    expect(layout.nodes).toHaveLength(5);
    const spots = layout.nodes.map((entry) => `${entry.x},${entry.y}`);
    expect(new Set(spots).size).toBe(5);
    expect(layout.edges).toHaveLength(4);
    expect(layout.nodes.find((entry) => entry.node.id === "a")).toMatchObject({ x: 0, y: 0 });
  });

  it("tolerates self-loops and keeps their path finite", () => {
    const layout = layoutGraph([room("a"), room("b")], [edge("ab", "a", "b"), edge("aa", "a", "a")], "a");

    const paths = layout.edges.map((entry) => entry.path);
    expect(new Set(paths).size).toBe(2);
    expect(paths.every((path) => !path.includes("NaN"))).toBe(true);
  });

  it("drops edges that reference unknown nodes instead of crashing", () => {
    const layout = layoutGraph([room("a")], [edge("ax", "a", "ghost")], "a");
    expect(layout.edges).toHaveLength(0);
    expect(layout.bounds.width).toBeGreaterThan(0);
  });

  it("keeps every fanned-out parallel edge curve and label inside the bounds", () => {
    // A corridor (one row) whose last pair is joined by four parallel/reciprocal edges plus a self-loop.
    const nodes = [room("a"), room("b"), room("c")];
    const edges = [
      edge("a-b", "a", "b"), edge("b-c1", "b", "c"), edge("b-c2", "b", "c"),
      edge("c-b1", "c", "b"), edge("c-b2", "c", "b"), edge("self", "c", "c"),
    ];
    const { edges: laid, bounds } = layoutGraph(nodes, edges, "a");

    for (const { labelX, labelY } of laid) {
      expect(labelX).toBeGreaterThanOrEqual(bounds.x);
      expect(labelX).toBeLessThanOrEqual(bounds.x + bounds.width);
      expect(labelY - 10).toBeGreaterThanOrEqual(bounds.y);
      expect(labelY + 10).toBeLessThanOrEqual(bounds.y + bounds.height);
    }
  });
});

const link = (source: string, target: string, label: string, kind: ExplorationEdge["kind"] = "exit"): ExplorationEdge => ({
  id: `${source}/${kind}/${label}`,
  source,
  target,
  kind,
  label,
  traversed: true,
});
const shown = (layout: ReturnType<typeof layoutGraph>) =>
  layout.edges.map(({ edge, reverse }) => `${edge.source}-${edge.label}->${edge.target}${reverse ? " (two-way)" : ""}`).sort();

describe("layoutGraph orientation", () => {
  const hall = [room("entry"), room("corridor")];
  const pair = [link("entry", "corridor", "north"), link("corridor", "entry", "south")];

  it("folds a reciprocal pair into one connection labelled from the room nearer the player", () => {
    expect(shown(layoutGraph(hall, pair, "entry"))).toEqual(["entry-north->corridor (two-way)"]);
    expect(shown(layoutGraph(hall, pair, "corridor"))).toEqual(["corridor-south->entry (two-way)"]);
  });

  it("does not depend on the order the engine lists edges", () => {
    expect(shown(layoutGraph(hall, [...pair].reverse(), "entry"))).toEqual(shown(layoutGraph(hall, pair, "entry")));
  });

  it("keeps orienting outward through intermediate rooms and re-orients when the player moves", () => {
    const nodes = [room("entry"), room("corridor"), room("library")];
    const edges = [
      link("entry", "corridor", "north"), link("corridor", "entry", "south"),
      link("corridor", "library", "east"), link("library", "corridor", "west"),
    ];
    expect(shown(layoutGraph(nodes, edges, "entry"))).toEqual([
      "corridor-east->library (two-way)",
      "entry-north->corridor (two-way)",
    ]);
    expect(shown(layoutGraph(nodes, edges, "library"))).toEqual([
      "corridor-south->entry (two-way)",
      "library-west->corridor (two-way)",
    ]);
  });

  it("orients each connection of a loop exactly once and deterministically", () => {
    const nodes = [room("a"), room("b"), room("c")];
    const edges = [
      link("a", "b", "north"), link("b", "a", "south"),
      link("b", "c", "east"), link("c", "b", "west"),
      link("c", "a", "southwest"), link("a", "c", "northeast"),
    ];
    const first = shown(layoutGraph(nodes, edges, "a"));
    expect(first).toHaveLength(3);
    expect(first).toContain("a-north->b (two-way)");
    expect(first).toContain("a-northeast->c (two-way)");
    // b and c share a depth: the tie breaks on source id, never on input order.
    expect(first).toContain("b-east->c (two-way)");
    expect(shown(layoutGraph(nodes, [...edges].reverse(), "a"))).toEqual(first);
  });

  it("never implies a one-way link is traversable backwards", () => {
    const nodes = [room("a"), room("b")];
    // The player stands at b but the only passage runs a -> b.
    expect(shown(layoutGraph(nodes, [link("a", "b", "down")], "b"))).toEqual(["a-down->b"]);
  });

  it("keeps routes, passages, parallel exits and frontiers as their own connections", () => {
    const nodes = [room("a"), room("b"), { id: "frontier-1", kind: "frontier" } as ExplorationNode];
    const edges = [
      link("a", "b", "stairs"), link("b", "a", "stairs"),
      link("a", "b", "bridge", "route"), link("b", "a", "bridge", "route"),
      link("a", "b", "unmapped passage", "passage"),
      link("a", "frontier-1", "west"),
    ];
    const out = shown(layoutGraph(nodes, edges, "a"));
    expect(out).toContain("a-stairs->b (two-way)");
    expect(out).toContain("a-bridge->b");
    expect(out).toContain("b-bridge->a");
    expect(out).toContain("a-unmapped passage->b");
    expect(out).toContain("a-west->frontier-1");
    expect(out).toHaveLength(5);
  });

  it("pairs several exits between two rooms only by named opposites", () => {
    const nodes = [room("a"), room("b")];
    const edges = [
      link("a", "b", "north"), link("a", "b", "up"),
      link("b", "a", "south"), link("b", "a", "hatch"),
    ];
    expect(shown(layoutGraph(nodes, edges, "a"))).toEqual([
      "a-north->b (two-way)",
      "a-up->b",
      "b-hatch->a",
    ]);
  });
});
