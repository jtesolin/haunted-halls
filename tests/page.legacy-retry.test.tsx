import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSession } from "next-auth/react";
import type { ChatSession } from "@/types/chat";
import Home from "@/app/page";

const reactStateSeam = vi.hoisted(() => ({
  useStateCalls: 0,
  initialSessions: null as ChatSession[] | null,
  initialActiveSessionId: "",
}));

vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();

  return {
    ...actual,
    useState: <T,>(initialState: T | (() => T)): [T, Dispatch<SetStateAction<T>>] => {
      reactStateSeam.useStateCalls += 1;

      if (reactStateSeam.useStateCalls === 1 && reactStateSeam.initialSessions) {
        return actual.useState(reactStateSeam.initialSessions) as unknown as [T, Dispatch<SetStateAction<T>>];
      }

      if (reactStateSeam.useStateCalls === 2 && reactStateSeam.initialActiveSessionId) {
        return actual.useState(reactStateSeam.initialActiveSessionId) as unknown as [T, Dispatch<SetStateAction<T>>];
      }

      return actual.useState(initialState);
    },
  };
});

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn(),
  SessionProvider: ({ children }: { children: ReactNode }) => children,
}));

const AMBIGUOUS_RETRY_MESSAGE = "Delivery could not be confirmed. You may safely retry.";
const REQUEST_ID_ERROR_MESSAGE = "Unable to securely prepare this message. Please try again.";

describe("legacy retry idempotency behavior", () => {
  beforeEach(() => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    vi.mocked(global.fetch).mockReset();
    vi.mocked(useSession).mockReset();
    window.history.replaceState({}, "", "/");
    reactStateSeam.useStateCalls = 0;
    reactStateSeam.initialActiveSessionId = "legacy-session";
    reactStateSeam.initialSessions = [
      {
        id: "legacy-session",
        title: "Legacy adventure",
        campaign_id: "campaign-123",
        last_message: "open the iron door",
        updated_at: Date.now(),
        conversation_loaded: true,
        messages: [
          {
            id: "legacy-failed-message",
            role: "user",
            text: "open the iron door",
            delivery_state: "failed",
            failure: {
              category: "ambiguous",
              retryable: true,
              message: AMBIGUOUS_RETRY_MESSAGE,
            },
          },
        ],
      },
    ];
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
        return new Promise<Response>(() => {});
      }
      if (String(input) === "/api/chat") {
        chatAttempts += 1;
        return Promise.resolve(new Response(JSON.stringify({ reply: "The hall answers." }), { status: 200 }));
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });

    const cryptoSource = globalThis.crypto;
    const originalRandomUUID = cryptoSource.randomUUID;
    const originalGetRandomValues = cryptoSource.getRandomValues;
    Object.defineProperty(cryptoSource, "randomUUID", { configurable: true, value: undefined });
    Object.defineProperty(cryptoSource, "getRandomValues", { configurable: true, value: undefined });

    try {
      render(<Home />);

      expect(await screen.findByText(AMBIGUOUS_RETRY_MESSAGE)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Retry sending/ })).toBeEnabled();

      fireEvent.click(screen.getByRole("button", { name: /Retry sending/ }));

      await waitFor(() => expect(screen.getByText(REQUEST_ID_ERROR_MESSAGE)).toBeInTheDocument());
      expect(chatAttempts).toBe(0);
      expect(screen.getByRole("button", { name: /Retry sending/ })).toBeEnabled();
      expect(screen.getByText(AMBIGUOUS_RETRY_MESSAGE)).toBeInTheDocument();
      expect(screen.queryByText("The narrator is responding...")).not.toBeInTheDocument();
    } finally {
      Object.defineProperty(cryptoSource, "randomUUID", { configurable: true, value: originalRandomUUID });
      Object.defineProperty(cryptoSource, "getRandomValues", { configurable: true, value: originalGetRandomValues });
    }
  });
});
