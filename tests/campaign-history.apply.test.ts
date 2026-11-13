import { describe, expect, it } from "vitest";
import { applyLoadedHistory } from "@/lib/campaign-history";
import type { ChatSession } from "@/types/chat";

const history = {
  title: "Server title",
  character_id: "char-1",
  messages: [{ id: "t1", role: "assistant" as const, text: "server history" }],
};

function session(overrides: Partial<ChatSession> = {}): ChatSession {
  return {
    id: "a",
    title: "Local title",
    campaign_id: "a",
    updated_at: 1,
    conversation_loaded: false,
    messages: [],
    ...overrides,
  };
}

describe("applyLoadedHistory", () => {
  it("loads history into a still-unloaded session and clears a previous failure", () => {
    const [result] = applyLoadedHistory([session({ history_load_failed: true })], "a", history, 99);

    expect(result.messages).toEqual(history.messages);
    expect(result).toMatchObject({
      title: "Server title",
      character_id: "char-1",
      conversation_loaded: true,
      history_load_failed: false,
      updated_at: 99,
    });
  });

  it("never overwrites a session that has been loaded since the request started", () => {
    const loaded = session({
      conversation_loaded: true,
      messages: [{ id: "local", role: "user", text: "open the door", delivery_state: "pending" }],
    });

    const [result] = applyLoadedHistory([loaded], "a", history, 99);

    expect(result).toBe(loaded);
  });

  it("never overwrites a failed local message on a loaded session", () => {
    const failed = session({
      conversation_loaded: true,
      messages: [
        {
          id: "local",
          role: "user",
          text: "open the door",
          delivery_state: "failed",
          failure: { category: "ambiguous", retryable: true, message: "retry" },
        },
      ],
    });

    const [result] = applyLoadedHistory([failed], "a", history, 99);

    expect(result.messages).toEqual(failed.messages);
  });

  it("only touches the targeted session", () => {
    const other = session({ id: "b", campaign_id: "b" });

    const [, untouchedOther] = applyLoadedHistory([session(), other], "a", history, 99);

    expect(untouchedOther).toBe(other);
  });
});
