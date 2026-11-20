import type { ExplorationEdge, ExplorationNode } from "@/types/exploration";

export const COL_W = 170;
export const ROW_H = 70;
export const ROOM_HALF = { w: 62, h: 18 };
export const FRONTIER_HALF = { w: 14, h: 14 };

export interface PositionedNode {
  node: ExplorationNode;
  x: number;
  y: number;
  half: { w: number; h: number };
}

export interface PositionedEdge {
  // The edge as the engine reports it. For a merged reciprocal pair this is the one leaving the
  // room nearer the player, so its label is the exit direction read outward from that room.
  edge: ExplorationEdge;
  // The opposite-direction engine edge folded into this connection; null for a single edge.
  reverse: ExplorationEdge | null;
  path: string;
  labelX: number;
  labelY: number;
}

export interface GraphLayout {
  nodes: PositionedNode[];
  edges: PositionedEdge[];
  bounds: { x: number; y: number; width: number; height: number };
}

type Point = { x: number; y: number };

// Where the ray from a node centre toward `toward` leaves the node's rectangle.
function clipToRect(center: Point, half: { w: number; h: number }, toward: Point): Point {
  const dx = toward.x - center.x;
  const dy = toward.y - center.y;
  if (dx === 0 && dy === 0) {
    return center;
  }
  const scale = Math.min(
    dx === 0 ? Infinity : half.w / Math.abs(dx),
    dy === 0 ? Infinity : half.h / Math.abs(dy)
  );
  return { x: center.x + dx * scale, y: center.y + dy * scale };
}

const OPPOSITE: Record<string, string> = {
  north: "south", east: "west", up: "down", in: "out", northeast: "southwest", northwest: "southeast",
};
for (const [a, b] of Object.entries(OPPOSITE)) {
  OPPOSITE[b] = a;
}

// Folds each reciprocal pair of exits (A->B and B->A) into one connection oriented away from the
// player (the endpoint with the smaller BFS depth is the source; ties break by id). Only exits fold:
// routes and passages keep their own semantics, and one-way links keep their real direction.
function connect(
  edges: ExplorationEdge[],
  byId: Map<string, { node: ExplorationNode }>,
  depthOf: Map<string, number>
): { edge: ExplorationEdge; reverse: ExplorationEdge | null }[] {
  const isRoom = (id: string) => byId.get(id)?.node.kind === "room";
  const folded = new Set<string>();
  const merged = new Map<string, { edge: ExplorationEdge; reverse: ExplorationEdge }>();
  const exits = edges.filter((e) => e.kind === "exit" && e.source !== e.target && isRoom(e.source) && isRoom(e.target));
  for (const out of exits) {
    if (folded.has(out.id)) continue;
    const back = exits.filter((e) => e.source === out.target && e.target === out.source);
    const siblings = exits.filter((e) => e.source === out.source && e.target === out.target);
    // Lone pair is unambiguous; with several exits per side only a named opposite pairs.
    const mate =
      siblings.length === 1 && back.length === 1 ? back[0] : back.find((e) => OPPOSITE[out.label] === e.label);
    if (!mate || folded.has(mate.id)) continue;
    folded.add(out.id);
    folded.add(mate.id);
    const near = (e: ExplorationEdge) => depthOf.get(e.source) ?? 0;
    const outward = near(mate) < near(out) || (near(mate) === near(out) && mate.source < out.source) ? mate : out;
    merged.set(outward.id, { edge: outward, reverse: outward === out ? mate : out });
  }
  return edges
    .filter((e) => !folded.has(e.id) || merged.has(e.id))
    .map((e) => merged.get(e.id) ?? { edge: e, reverse: null });
}

// Layered layout from the start node. Layout need not be geographic: it only has to be
// stable, readable, and cope with branches, cycles, and disconnected pieces.
export function layoutGraph(nodes: ExplorationNode[], edges: ExplorationEdge[], startId: string): GraphLayout {
  const known = new Set(nodes.map((node) => node.id));
  const usable = edges.filter((edge) => known.has(edge.source) && known.has(edge.target));
  const neighbours = new Map<string, string[]>();
  // Edge order from the engine is not a contract; sort so layout never depends on it.
  const ordered = [...usable].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  for (const edge of ordered) {
    neighbours.set(edge.source, [...(neighbours.get(edge.source) ?? []), edge.target]);
    neighbours.set(edge.target, [...(neighbours.get(edge.target) ?? []), edge.source]);
  }

  const depthOf = new Map<string, number>();
  const rowsAtDepth = new Map<number, number>();
  const place = new Map<string, Point>();
  const visit = (root: string) => {
    const queue = [root];
    depthOf.set(root, 0);
    while (queue.length > 0) {
      const id = queue.shift()!;
      const depth = depthOf.get(id)!;
      const row = rowsAtDepth.get(depth) ?? 0;
      rowsAtDepth.set(depth, row + 1);
      place.set(id, { x: depth * COL_W, y: row * ROW_H });
      for (const next of neighbours.get(id) ?? []) {
        if (!depthOf.has(next)) {
          depthOf.set(next, depth + 1);
          queue.push(next);
        }
      }
    }
  };
  if (known.has(startId)) {
    visit(startId);
  }
  for (const node of nodes) {
    if (!depthOf.has(node.id)) {
      visit(node.id);
    }
  }

  const positioned: PositionedNode[] = nodes.map((node) => ({
    node,
    ...place.get(node.id)!,
    half: node.kind === "room" ? ROOM_HALF : FRONTIER_HALF,
  }));
  const byId = new Map(positioned.map((entry) => [entry.node.id, entry]));

  const connections = connect(ordered, byId, depthOf);

  // Parallel connections between one pair fan out so none hide another.
  const pairCount = new Map<string, number>();
  const pairSeen = new Map<string, number>();
  const pairKey = (edge: ExplorationEdge) => [edge.source, edge.target].sort().join("\u0000");
  for (const { edge } of connections) {
    pairCount.set(pairKey(edge), (pairCount.get(pairKey(edge)) ?? 0) + 1);
  }

  const positionedEdges: PositionedEdge[] = connections.map(({ edge, reverse }) => {
    const from = byId.get(edge.source)!;
    const to = byId.get(edge.target)!;
    if (edge.source === edge.target) {
      const top = from.y - from.half.h;
      return {
        edge,
        reverse,
        path: `M ${from.x - 10} ${top} C ${from.x - 30} ${top - 44}, ${from.x + 30} ${top - 44}, ${from.x + 10} ${top}`,
        labelX: from.x,
        labelY: top - 36,
      };
    }
    const key = pairKey(edge);
    const index = pairSeen.get(key) ?? 0;
    pairSeen.set(key, index + 1);
    const count = pairCount.get(key)!;
    // Normal is taken from the canonical (sorted) direction so opposite edges separate.
    const forward = edge.source < edge.target;
    const dx = (forward ? to.x - from.x : from.x - to.x) || 0;
    const dy = (forward ? to.y - from.y : from.y - to.y) || 0;
    const length = Math.hypot(dx, dy) || 1;
    const offset = (index - (count - 1) / 2) * 44;
    const control = {
      x: (from.x + to.x) / 2 + (-dy / length) * offset * 2,
      y: (from.y + to.y) / 2 + (dx / length) * offset * 2,
    };
    const start = clipToRect(from, from.half, control);
    const end = clipToRect(to, to.half, control);
    return {
      edge,
      reverse,
      path: `M ${start.x} ${start.y} Q ${control.x} ${control.y} ${end.x} ${end.y}`,
      labelX: 0.25 * start.x + 0.5 * control.x + 0.25 * end.x,
      labelY: 0.25 * start.y + 0.5 * control.y + 0.25 * end.y,
    };
  });

  // Bounds cover node boxes plus every edge label/curve peak, so fanned-out parallel edges and
  // self-loops are never clipped by "fit whole map".
  const LABEL_HALF = { w: 50, h: 20 };
  const left = [...positioned.map((n) => n.x - n.half.w), ...positionedEdges.map((e) => e.labelX - LABEL_HALF.w)];
  const right = [...positioned.map((n) => n.x + n.half.w), ...positionedEdges.map((e) => e.labelX + LABEL_HALF.w)];
  const top = [...positioned.map((n) => n.y - n.half.h - 36), ...positionedEdges.map((e) => e.labelY - LABEL_HALF.h)];
  const bottom = [...positioned.map((n) => n.y + n.half.h), ...positionedEdges.map((e) => e.labelY + LABEL_HALF.h)];
  const pad = 35;
  const minX = Math.min(...left, 0) - pad;
  const minY = Math.min(...top, 0) - pad;
  return {
    nodes: positioned,
    edges: positionedEdges,
    bounds: {
      x: minX,
      y: minY,
      width: Math.max(...right, 0) + pad - minX,
      height: Math.max(...bottom, 0) + pad - minY,
    },
  };
}
