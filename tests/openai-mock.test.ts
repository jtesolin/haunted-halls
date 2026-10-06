/* @vitest-environment node */

import type { Server } from "node:http";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMockResponse, E2E_OPENAI_KEY, LOOK_AROUND_TEXT, OPENING_TEXT } from "@/playwright/openai-mock/responses";
import { createMockServer } from "@/playwright/openai-mock/server";
import structuredContracts from "@/playwright/openai-mock/structured-contracts.json";

const narrator = "You are the AI narrator for a haunted halls adventure.";
const message = (role: string, text: string) => ({
  role, content: [{ type: "input_text", text }],
});
const textRequest = (text: string) => ({
  model: "e2e-test-model",
  input: [message("developer", narrator), message("user", "Current scene (authoritative, observable now):\n{}"), message("user", text)],
});
const structuredRequest = (name: string, text = "Player text:\nlook around") => ({
  model: "e2e-test-model", input: [message("user", text)],
  text: { format: { type: "json_schema", name, strict: true,
    schema: Object.hasOwn(structuredContracts, name)
      ? structuredClone(structuredContracts[name as keyof typeof structuredContracts])
      : undefined } },
});
const invalidSchemas: unknown[] = [undefined, null, "not-an-object", 1, true, [], {}, { type: "object" },
  structuredContracts.DirectorProposalResponse];

function reordered(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(reordered);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).reverse().map(([key, entry]) => [key, reordered(entry)]));
  }
  return value;
}

function nestedMutation() {
  const schema = structuredClone(structuredContracts.ActionParserOutput);
  schema.$defs.ActionParserParameters.properties.amount.anyOf[0].type = "string";
  return schema;
}
const output = (request: unknown) => createMockResponse(request).output[0].content[0].text;

describe("local OpenAI Responses fixtures", () => {
  it.each(Object.keys(structuredContracts))("accepts the real %s contract with reordered object keys", (name) => {
    const request = structuredRequest(name);
    expect(() => createMockResponse({
      ...request, text: { format: { ...request.text.format, schema: reordered(request.text.format.schema) } },
    })).not.toThrow();
  });

  it.each(invalidSchemas)("rejects malformed/unrelated recognized schemas %#", (schema) => {
    const request = structuredRequest("ActionParserOutput");
    expect(() => createMockResponse({
      ...request, text: { format: { ...request.text.format, schema } },
    })).toThrow("Unsupported Structured Outputs schema contract");
  });

  it("rejects a meaningful nested schema mutation before fixture dispatch", () => {
    const request = structuredRequest("ActionParserOutput");
    request.text.format.schema = nestedMutation();
    expect(() => createMockResponse(request)).toThrow("Unsupported Structured Outputs schema contract");
  });

  it("routes all three structured formats and includes strict nullable fields", () => {
    expect(JSON.parse(output(structuredRequest("StarterAbilityProviderGeneration")))).toEqual({
      sensory_ability: {
        ability_id: "echo_sense", display_name: "Echo Sense",
        description: "Sense nearby active presence.", track: "investigation", sense_filter: "presence", range: 0,
      },
      utility_ability: {
        ability_id: "gentle_pull", display_name: "Gentle Pull",
        description: "Draw a small nearby portable object toward your hand.", track: "resolve", operation: "retrieve",
      },
    });
    expect(JSON.parse(output(structuredRequest("ActionParserOutput")))).toMatchObject({
      action: "observe", target: null, confidence: 1, parse_status: "ok", parser_notes: null,
    });
    expect(JSON.parse(output(structuredRequest("ActionParserOutput", "Player text:\nexamine the lantern")))).toHaveProperty("target", "lantern");
    expect(JSON.parse(output(structuredRequest("DirectorProposalResponse")))).toEqual({
      proposal: { decision: "none", world_action: null },
    });
  });

  it("routes narration and titles independently of request order and old history", () => {
    const look = textRequest("look around");
    look.input.splice(1, 0, message("assistant", "Old opening scene: unrelated"));
    expect(output(look)).toBe(LOOK_AROUND_TEXT);
    expect(output(textRequest("Based on the campaign opening below, provide only a short haunted campaign title with no quotes and no extra commentary.\n\nOpening"))).toBe("The Lantern's Vigil");
    expect(output(textRequest("Using the authoritative current scene provided, write the opening scene for this haunted halls campaign. More instructions."))).toBe(OPENING_TEXT);
    expect(output(textRequest("examine the lantern"))).toContain("The lantern glows softly");
    expect(output(look)).toBe(LOOK_AROUND_TEXT);
  });

  it("supports plain-text summary and JSON-array reflection responses", () => {
    expect(output({
      model: "e2e", input: [message("developer", "Summarize the campaign in 2-4 sentences."), message("user", "Existing summary:\nNone yet.")],
    })).toContain("Entry Hall");
    expect(JSON.parse(output({
      model: "e2e", input: [message("developer", "What important long-term facts should be remembered?"), message("user", "Campaign state:\n{}")],
    }))).toEqual(["The player began exploring the Entry Hall."]);
  });

  it("returns the Responses SDK message/content/usage envelope", () => {
    const response = createMockResponse(textRequest("look around"));
    expect(response).toMatchObject({
      object: "response", status: "completed", error: null, incomplete_details: null,
      output: [{ type: "message", role: "assistant", status: "completed",
        content: [{ type: "output_text", text: LOOK_AROUND_TEXT, annotations: [] }] }],
      usage: { input_tokens: 100, output_tokens: 30, total_tokens: 130,
        input_tokens_details: { cached_tokens: 0 }, output_tokens_details: { reasoning_tokens: 0 } },
    });
  });

  it.each([
    structuredRequest("UnknownFormat"),
    structuredRequest("ActionParserOutput", "Player text:\nunsupported"),
    textRequest("unknown command"),
    { ...textRequest("look around"), stream: true },
    { ...textRequest("look around"), tools: [{ type: "web_search" }] },
    { ...textRequest("look around"), input: [] },
    { ...textRequest("look around"), text: { format: { type: "json_object" } } },
    { model: "e2e", input: [message("developer", "unknown prompt")] },
  ])("fails loudly on unsupported requests %#", (request) => {
    expect(() => createMockResponse(request)).toThrow();
  });
});

describe("local OpenAI HTTP boundary", () => {
  let server: Server | undefined;
  afterEach(async () => {
    vi.restoreAllMocks();
    await new Promise<void>((resolve, reject) => {
      if (!server) return resolve();
      server.close((error) => error ? reject(error) : resolve());
      server.closeAllConnections();
    });
  });
  async function start() {
    server = createMockServer();
    await new Promise<void>((resolve) => server?.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("Missing mock address");
    return `http://127.0.0.1:${address.port}`;
  }

  it("serves the local SDK endpoint and health check", async () => {
    const base = await start();
    expect((await fetch(`${base}/health`)).status).toBe(200);
    const response = await fetch(`${base}/v1/responses`, {
      method: "POST", headers: { authorization: `Bearer ${E2E_OPENAI_KEY}` },
      body: JSON.stringify(textRequest("look around")),
    });
    expect(response.status).toBe(200);
    expect(await response.json()).toHaveProperty("status", "completed");
  });

  it("rejects non-test credentials, unsupported endpoints, malformed JSON, and prompts", async () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    const base = await start();
    expect((await fetch(`${base}/v1/responses`, {
      method: "POST", headers: { authorization: "Bearer not-the-e2e-key" },
    })).status).toBe(401);
    expect((await fetch(`${base}/v1/chat/completions`, { method: "POST" })).status).toBe(404);
    for (const body of ["{", JSON.stringify(textRequest("unsupported"))]) {
      expect((await fetch(`${base}/v1/responses`, {
        method: "POST", headers: { authorization: `Bearer ${E2E_OPENAI_KEY}` }, body,
      })).status).toBe(400);
    }
    expect(log).toHaveBeenCalled();
  });

  it("returns HTTP 400 for malformed and nested-mutated structured contracts", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const base = await start();
    const request = structuredRequest("ActionParserOutput");
    for (const schema of [...invalidSchemas, nestedMutation()]) {
      const response = await fetch(`${base}/v1/responses`, {
        method: "POST", headers: { authorization: `Bearer ${E2E_OPENAI_KEY}` },
        body: JSON.stringify({ ...request, text: { format: { ...request.text.format, schema } } }),
      });
      expect(response.status).toBe(400);
      expect(await response.json()).toHaveProperty("error.code", "unsupported_e2e_request");
    }
  });
});
