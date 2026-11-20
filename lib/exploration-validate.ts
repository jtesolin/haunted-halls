import type { ExplorationResponse, ExplorationRoomNotes } from "@/types/exploration";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isString = (value: unknown): value is string => typeof value === "string";
const isStringArray = (value: unknown): value is string[] => Array.isArray(value) && value.every(isString);
const EDGE_KINDS = new Set(["exit", "route", "passage"]);

function isLocation(value: unknown) {
  return isRecord(value) && isString(value.id) && isString(value.name);
}

// Trust boundary: the engine payload is checked field by field so malformed JSON takes the
// error path instead of throwing during render. Returns null when any field is invalid.
export function parseExploration(body: unknown): ExplorationResponse | null {
  if (!isRecord(body) || !isLocation(body.current_location) || !isStringArray(body.observations)) {
    return null;
  }
  if (!Array.isArray(body.nodes) || !Array.isArray(body.edges)) {
    return null;
  }
  const nodesOk = body.nodes.every(
    (node) =>
      isRecord(node) &&
      isString(node.id) &&
      (node.kind === "frontier" || (node.kind === "room" && isString(node.name))) &&
      (node.name === undefined || node.name === null || isString(node.name))
  );
  const edgesOk = body.edges.every(
    (edge) =>
      isRecord(edge) &&
      isString(edge.id) &&
      isString(edge.source) &&
      isString(edge.target) &&
      EDGE_KINDS.has(edge.kind as string) &&
      isString(edge.label) &&
      typeof edge.traversed === "boolean"
  );
  return nodesOk && edgesOk ? (body as unknown as ExplorationResponse) : null;
}

export function parseRoomNotes(body: unknown): ExplorationRoomNotes | null {
  if (!isRecord(body) || !isLocation(body.room) || !isStringArray(body.notes) || typeof body.current !== "boolean") {
    return null;
  }
  return body as unknown as ExplorationRoomNotes;
}
