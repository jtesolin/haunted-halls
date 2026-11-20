import { describe, expect, it } from "vitest";
import { parseExploration, parseRoomNotes } from "@/lib/exploration-validate";

const GOOD = {
  current_location: { id: "hall", name: "Hall" },
  nodes: [
    { id: "hall", kind: "room", name: "Hall" },
    { id: "frontier-1", kind: "frontier", name: null },
  ],
  edges: [{ id: "e", source: "hall", target: "frontier-1", kind: "exit", label: "door", traversed: false }],
  observations: ["A hearth."],
};

describe("parseExploration", () => {
  it("accepts a valid payload", () => {
    expect(parseExploration(GOOD)).toEqual(GOOD);
  });

  it.each([
    ["null body", null],
    ["null node", { ...GOOD, nodes: [null] }],
    ["null edge", { ...GOOD, edges: [null] }],
    ["unknown node kind", { ...GOOD, nodes: [{ id: "x", kind: "cellar" }] }],
    ["room without a name", { ...GOOD, nodes: [{ id: "x", kind: "room" }] }],
    ["non-string node id", { ...GOOD, nodes: [{ id: 1, kind: "room", name: "x" }] }],
    ["bad edge kind", { ...GOOD, edges: [{ ...GOOD.edges[0], kind: "teleport" }] }],
    ["edge missing source", { ...GOOD, edges: [{ ...GOOD.edges[0], source: undefined }] }],
    ["non-string observation", { ...GOOD, observations: [null] }],
    ["current location without name", { ...GOOD, current_location: { id: "hall" } }],
  ])("rejects %s", (_name, body) => {
    expect(parseExploration(body)).toBeNull();
  });
});

describe("parseRoomNotes", () => {
  const room = { room: { id: "library", name: "Library" }, current: false, notes: ["n"] };

  it("accepts a valid payload", () => {
    expect(parseRoomNotes(room)).toEqual(room);
  });

  it.each([
    ["null note", { ...room, notes: [null] }],
    ["object note", { ...room, notes: [{ text: "x" }] }],
    ["missing room id", { ...room, room: { name: "Library" } }],
    ["notes not an array", { ...room, notes: "n" }],
  ])("rejects %s", (_name, body) => {
    expect(parseRoomNotes(body)).toBeNull();
  });
});
