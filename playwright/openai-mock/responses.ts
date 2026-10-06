export const E2E_OPENAI_KEY = "e2e-only-fake-openai-key-not-a-secret";
export const OPENING_TEXT =
  "You stand in the Entry Hall. A lantern casts long shadows across the dusty floor. What do you do next?";
export const LOOK_AROUND_TEXT =
  "The lantern casts a steady light across the Entry Hall. What will you examine next?";

export class UnsupportedRequestError extends Error {}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new UnsupportedRequestError("Expected an object");
  }
  return value as Record<string, unknown>;
}

function messages(input: unknown): Array<{ role: string; text: string }> {
  if (!Array.isArray(input) || input.length === 0) {
    throw new UnsupportedRequestError("Expected Responses input messages");
  }
  return input.map((value) => {
    const message = record(value);
    if (!["developer", "system", "user", "assistant"].includes(String(message.role))) {
      throw new UnsupportedRequestError("Unsupported input role");
    }
    if (!Array.isArray(message.content) || message.content.length === 0) {
      throw new UnsupportedRequestError("Expected text content parts");
    }
    const text = message.content.map((value) => {
      const part = record(value);
      if (!["input_text", "output_text"].includes(String(part.type)) || typeof part.text !== "string") {
        throw new UnsupportedRequestError("Unsupported content part");
      }
      return part.text;
    }).join("\n");
    return { role: String(message.role), text };
  });
}

function structuredOutput(name: unknown, input: ReturnType<typeof messages>) {
  switch (name) {
    case "StarterAbilityProviderGeneration":
      return {
        sensory_ability: {
          ability_id: "echo_sense", display_name: "Echo Sense",
          description: "Sense nearby active presence.", track: "investigation",
          sense_filter: "presence", range: 0,
        },
        utility_ability: {
          ability_id: "gentle_pull", display_name: "Gentle Pull",
          description: "Draw a small nearby portable object toward your hand.",
          track: "resolve", operation: "retrieve",
        },
      };
    case "ActionParserOutput": {
      const playerText = input.at(-1)?.text;
      if (playerText !== "Player text:\nlook around" && playerText !== "Player text:\nexamine the lantern") {
        throw new UnsupportedRequestError("Unsupported Action Parser command");
      }
      return {
        action: "observe",
        target: playerText === "Player text:\nexamine the lantern" ? "lantern" : null,
        parameters: {
          item: null, amount: null, duration: null, with_item: null,
          interaction_mode: null, ability_id: null,
        },
        stealth: false, confidence: 1, parse_status: "ok", parser_notes: null,
      };
    }
    case "DirectorProposalResponse":
      return { proposal: { decision: "none", world_action: null } };
    default:
      throw new UnsupportedRequestError("Unsupported Structured Outputs format name");
  }
}

function textOutput(input: ReturnType<typeof messages>): string {
  const instruction = input.find((message) => message.role === "developer")?.text ?? "";
  const lastUserText = input.filter((message) => message.role === "user").at(-1)?.text ?? "";
  if (instruction.startsWith("Summarize the campaign in 2-4 sentences.") &&
      lastUserText.startsWith("Existing summary:\n")) {
    return "The player explored the Entry Hall and examined its lantern. The halls remain unexplored.";
  }
  if (instruction.startsWith("What important long-term facts should be remembered?") &&
      lastUserText.startsWith("Campaign state:\n")) {
    return JSON.stringify(["The player began exploring the Entry Hall."]);
  }
  if (!instruction.startsWith("You are the AI narrator for a haunted halls adventure.") ||
      !input.some((message) => message.text.startsWith("Current scene (authoritative, observable now):\n"))) {
    throw new UnsupportedRequestError("Unsupported text-generation prompt");
  }
  if (lastUserText.startsWith(
    "Using the authoritative current scene provided, write the opening scene for this haunted halls campaign."
  )) {
    return OPENING_TEXT;
  }
  if (lastUserText.startsWith(
    "Based on the campaign opening below, provide only a short haunted campaign title with no quotes and no extra commentary.\n\n"
  )) {
    return "The Lantern's Vigil";
  }
  if (lastUserText === "look around") return LOOK_AROUND_TEXT;
  if (lastUserText === "examine the lantern") {
    return "The lantern glows softly, its worn frame warm in the quiet hall. What do you do next?";
  }
  throw new UnsupportedRequestError("Unsupported narrator request");
}

export function createMockResponse(value: unknown) {
  const request = record(value);
  if (typeof request.model !== "string" || !request.model.trim() ||
      request.stream === true || (request.tools !== undefined &&
        (!Array.isArray(request.tools) || request.tools.length > 0))) {
    throw new UnsupportedRequestError("Unsupported model, streaming, or tools request");
  }
  const input = messages(request.input);
  const text = request.text === undefined ? undefined : record(request.text);
  const format = text?.format === undefined ? undefined : record(text.format);
  let outputText: string;
  if (format?.type === "json_schema") {
    if (format.strict !== true || !format.schema) {
      throw new UnsupportedRequestError("Expected strict Structured Outputs schema");
    }
    outputText = JSON.stringify(structuredOutput(format.name, input));
  } else if (!format || format.type === "text") {
    outputText = textOutput(input);
  } else {
    throw new UnsupportedRequestError("Unsupported response format");
  }

  return {
    id: "resp_e2e", object: "response", created_at: 1_700_000_000,
    status: "completed", error: null, incomplete_details: null,
    model: request.model, instructions: null, max_output_tokens: request.max_output_tokens ?? null,
    output: [{
      id: "msg_e2e", type: "message", status: "completed", role: "assistant",
      content: [{ type: "output_text", text: outputText, annotations: [], logprobs: [] }],
    }],
    parallel_tool_calls: false, previous_response_id: null,
    reasoning: request.reasoning ?? { effort: null, summary: null },
    store: false, temperature: 1, text: text ?? { format: { type: "text" } },
    tool_choice: "auto", tools: [], top_p: 1, truncation: "disabled",
    usage: {
      input_tokens: 100, input_tokens_details: { cached_tokens: 0 },
      output_tokens: 30, output_tokens_details: { reasoning_tokens: 0 }, total_tokens: 130,
    },
    metadata: {},
  };
}
