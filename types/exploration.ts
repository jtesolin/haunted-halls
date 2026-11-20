// Mirrors the engine's exploration projection (haunted-halls-engine app/schemas/exploration.py).
export interface ExplorationNode {
  id: string;
  kind: "room" | "frontier";
  name?: string | null;
}

export interface ExplorationEdge {
  id: string;
  source: string;
  target: string;
  kind: "exit" | "route" | "passage";
  label: string;
  traversed: boolean;
}

export interface ExplorationLocation {
  id: string;
  name: string;
}

export interface ExplorationResponse {
  current_location: ExplorationLocation;
  nodes: ExplorationNode[];
  edges: ExplorationEdge[];
  observations: string[];
}

export interface ExplorationRoomNotes {
  room: ExplorationLocation;
  current: boolean;
  notes: string[];
}
