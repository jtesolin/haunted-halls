import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSession } from "next-auth/react";
import type { ChatMessage } from "@/types/chat";
import Home from "@/app/page";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn(),
  SessionProvider: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("@/components/ConversationView", () => ({
  default: ({
    messages,
    onRetry,
    retryDisabled = false,
  }: {
    messages: ChatMessage[];
    onRetry?: (messageId: string) => void;
    retryDisabled?: boolean;
  }) => (
    <div>
      {messages.map((message) => {
        if (message.failure?.retryable) {
          const handleRetry = () => {
            delete message.request_id;
            onRetry?.(message.id);
          };
          return (
            <div key={message.id}>
              <p>{message.text}</p>
              <p>{message.failure.message}</p>
              <button
                type="button"
                disabled={retryDisabled}
                onClick={handleRetry}
                aria-label={`Retry sending: ${message.text}`}
              >
                Retry
              </button>
            </div>
          );
        }

        return (
          <div key={message.id}>
            {!message.is_loading ? <p>{message.text}</p> : null}
            {message.is_loading ? <p>{message.loading_text ?? "Loading..."}</p> : null}
            {message.failure ? <p>{message.failure.message}</p> : null}
          </div>
        );
      })}
    </div>
  ),
}));

const AMBIGUOUS_RETRY_MESSAGE = "Delivery could not be confirmed. You may safely retry.";
const REQUEST_ID_ERROR_MESSAGE = "Unable to securely prepare this message. Please try again.";

describe("legacy retry idempotency behavior", () => {
  beforeEach(() => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    vi.mocked(global.fetch).mockReset();
    vi.mocked(useSession).mockReset();
    window.history.replaceState({}, "", "/");
  });

  it("keeps a legacy failed message retryable and skips chat when Retry cannot generate a secure request ID", async () => {
    vi.mocked(useSession).mockReturnValue({
      data: { user: { name: "Player One", email: "player@example.com", image: null }, expires: "2099-01-01T00:00:00.000Z" },
      status: "authenticated",
      update: vi.fn(),
    });

    let chatAttempts = 0;
    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === "/api/campaigns") {
        return Promise.resolve(new Response("[]", { status: 200 }));
      }
      if (String(input) === "/api/campaign") {
        return Promise.resolve(new Response(JSON.stringify({
          campaign_id: "campaign-123",
          name: "The Lost Crypt",
          description: null,
          messages: [],
          truncated: false,
        }), { status: 200 }));
      }
      if (String(input) === "/api/chat") {
        chatAttempts += 1;
        return Promise.resolve(new Response(JSON.stringify({ error: "The hall failed." }), { status: 500 }));
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });

    render(<Home />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith("/api/campaign", expect.anything()));
    const textarea = await screen.findByRole("textbox", { name: "Enter your command" });
    fireEvent.change(textarea, { target: { value: "open the iron door" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByText(AMBIGUOUS_RETRY_MESSAGE)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Retry sending/ })).toBeEnabled();
    expect(chatAttempts).toBe(1);

    const cryptoSource = globalThis.crypto;
    const originalRandomUUID = cryptoSource.randomUUID;
    const originalGetRandomValues = cryptoSource.getRandomValues;
    Object.defineProperty(cryptoSource, "randomUUID", { configurable: true, value: undefined });
    Object.defineProperty(cryptoSource, "getRandomValues", { configurable: true, value: undefined });

    try {
      fireEvent.click(screen.getByRole("button", { name: /Retry sending/ }));

      await waitFor(() => expect(screen.getByText(REQUEST_ID_ERROR_MESSAGE)).toBeInTheDocument());
      expect(chatAttempts).toBe(1);
      expect(screen.getByRole("button", { name: /Retry sending/ })).toBeEnabled();
      expect(screen.queryByText("The narrator is responding...")).not.toBeInTheDocument();
    } finally {
      Object.defineProperty(cryptoSource, "randomUUID", { configurable: true, value: originalRandomUUID });
      Object.defineProperty(cryptoSource, "getRandomValues", { configurable: true, value: originalGetRandomValues });
    }
  });
});
