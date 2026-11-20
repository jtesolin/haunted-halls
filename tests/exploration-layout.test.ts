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

  it("keeps reciprocal and one-way edges as separate, distinct paths and tolerates self-loops", () => {
    const layout = layoutGraph(
      [room("a"), room("b")],
      [edge("ab", "a", "b"), edge("ba", "b", "a"), edge("aa", "a", "a")],
      "a"
    );

    const paths = layout.edges.map((entry) => entry.path);
    expect(new Set(paths).size).toBe(3);
    expect(paths.every((path) => !path.includes("NaN"))).toBe(true);
  });

  it("drops edges that reference unknown nodes instead of crashing", () => {
    const layout = layoutGraph([room("a")], [edge("ax", "a", "ghost")], "a");
    expect(layout.edges).toHaveLength(0);
    expect(layout.bounds.width).toBeGreaterThan(0);
  });
});
