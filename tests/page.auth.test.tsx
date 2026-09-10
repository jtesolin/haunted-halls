import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Home from "@/app/page";
import ChatInput from "@/components/ChatInput";
import { signIn, signOut, useSession } from "next-auth/react";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn(),
  SessionProvider: ({ children }: { children: ReactNode }) => children,
}));

const UUID_V4_PATTERN = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$/;
const AMBIGUOUS_RETRY_MESSAGE = "Delivery could not be confirmed. You may safely retry.";

describe("home auth gating", () => {
  beforeEach(() => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    vi.mocked(global.fetch).mockReset();
    vi.mocked(global.fetch).mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    window.history.replaceState({}, "", "/");
  });

  it("renders signed-out prompt, sign-in button, and no player id input", () => {
    vi.mocked(useSession).mockReturnValue({
      data: null,
      status: "unauthenticated",
      update: vi.fn(),
    });

    render(<Home />);

    expect(screen.getByText("Sign in to play")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in with Google" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Player ID")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Enter your command" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Create new campaign" })).toBeDisabled();
  });

  it("shows loading state without signed-in or signed-out controls", () => {
    vi.mocked(useSession).mockReturnValue({
      data: null,
      status: "loading",
      update: vi.fn(),
    });

    render(<Home />);

    expect(screen.getAllByText("Checking sign-in...").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Sign in with Google" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });

  it("shows profile fallback to email and enables controls when authenticated", async () => {
    vi.mocked(useSession).mockReturnValue({
      data: {
        user: { name: null, email: "player@example.com", image: null },
        expires: "2099-01-01T00:00:00.000Z",
      },
      status: "authenticated",
      update: vi.fn(),
    });

    render(<Home />);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith("/api/campaigns");
    });

    expect(screen.getAllByText("player@example.com").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Enter your command" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Create new campaign" })).toBeEnabled();
  });

  it("shows generic auth error and keeps sign-in retry action", () => {
    vi.mocked(useSession).mockReturnValue({
      data: null,
      status: "unauthenticated",
      update: vi.fn(),
    });
    window.history.replaceState({}, "", "/?error=AccessDenied");

    render(<Home />);

    expect(screen.getByText("Sign-in failed. Please try again.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in with Google" })).toBeInTheDocument();
  });

  it("calls nextauth signout action", () => {
    vi.mocked(useSession).mockReturnValue({
      data: {
        user: { name: "Player One", email: "player@example.com", image: null },
        expires: "2099-01-01T00:00:00.000Z",
      },
      status: "authenticated",
      update: vi.fn(),
    });

    render(<Home />);

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(signOut).toHaveBeenCalledWith({ callbackUrl: "/" });
  });

  it("starts google sign-in flow", () => {
    vi.mocked(useSession).mockReturnValue({
      data: null,
      status: "unauthenticated",
      update: vi.fn(),
    });

    render(<Home />);

    fireEvent.click(screen.getByRole("button", { name: "Sign in with Google" }));
    expect(signIn).toHaveBeenCalledWith("google", expect.objectContaining({ callbackUrl: "/" }));
  });

  it("keeps the composer enabled and focused while a narration request is in flight", async () => {
    vi.mocked(useSession).mockReturnValue({
      data: {
        user: { name: "Player One", email: "player@example.com", image: null },
        expires: "2099-01-01T00:00:00.000Z",
      },
      status: "authenticated",
      update: vi.fn(),
    });

    let resolveCampaignRequest: ((value: Response) => void) | undefined;
    const campaignRequest = new Promise<Response>((resolve) => {
      resolveCampaignRequest = resolve;
    });
    let resolveChatRequest: ((value: Response) => void) | undefined;
    const chatRequest = new Promise<Response>((resolve) => {
      resolveChatRequest = resolve;
    });

    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === "/api/campaigns") {
        return Promise.resolve(
          new Response(JSON.stringify([]), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        );
      }

      if (String(input) === "/api/campaign") {
        return campaignRequest;
      }

      if (String(input) === "/api/chat") {
        return chatRequest;
      }

      return Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );
    });

    render(<Home />);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith("/api/campaigns");
    });

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith("/api/campaign", expect.anything());
    });

    resolveCampaignRequest?.(
      new Response(JSON.stringify({
        campaign_id: "campaign-123",
        name: "The Lost Crypt",
        description: null,
        messages: [],
        truncated: false,
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Enter your command" })).toBeEnabled();
    });

    const textarea = screen.getByRole("textbox", { name: "Enter your command" });
    textarea.focus();
    fireEvent.change(textarea, { target: { value: "look around" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getAllByText("look around").length).toBeGreaterThan(0);
      expect(screen.getAllByText("The narrator is responding...").length).toBeGreaterThan(0);
    });

    expect(textarea).toBeEnabled();
    expect(textarea).toHaveFocus();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

    fireEvent.change(textarea, { target: { value: "go north" } });
    expect(textarea).toHaveValue("go north");
    fireEvent.keyDown(textarea, { key: "Enter", code: "Enter" });

    expect(
      vi.mocked(global.fetch).mock.calls.filter(([input]) => String(input) === "/api/chat")
    ).toHaveLength(1);
    expect(textarea).toHaveValue("go north");

    resolveChatRequest?.(
      new Response(JSON.stringify({ reply: "The hall answers." }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    await waitFor(() => {
      expect(screen.getAllByText("The hall answers.").length).toBeGreaterThan(0);
    });

    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
    expect(textarea).toHaveValue("go north");
    expect(textarea).toHaveFocus();
  });

  it("removes the temporary loading narrator message on chat failure", async () => {
    vi.mocked(useSession).mockReturnValue({
      data: {
        user: { name: "Player One", email: "player@example.com", image: null },
        expires: "2099-01-01T00:00:00.000Z",
      },
      status: "authenticated",
      update: vi.fn(),
    });

    let resolveCampaignRequest: ((value: Response) => void) | undefined;
    const campaignRequest = new Promise<Response>((resolve) => {
      resolveCampaignRequest = resolve;
    });
    let resolveChatRequest: ((value: Response) => void) | undefined;
    const chatRequest = new Promise<Response>((resolve) => {
      resolveChatRequest = resolve;
    });

    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === "/api/campaigns") {
        return Promise.resolve(
          new Response(JSON.stringify([]), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        );
      }

      if (String(input) === "/api/campaign") {
        return campaignRequest;
      }

      if (String(input) === "/api/chat") {
        return chatRequest;
      }

      return Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );
    });

    render(<Home />);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith("/api/campaigns");
    });

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith("/api/campaign", expect.anything());
    });

    resolveCampaignRequest?.(
      new Response(JSON.stringify({
        campaign_id: "campaign-123",
        name: "The Lost Crypt",
        description: null,
        messages: [],
        truncated: false,
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Enter your command" })).toBeEnabled();
    });

    const textarea = screen.getByRole("textbox", { name: "Enter your command" });
    fireEvent.change(textarea, { target: { value: "look around" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getAllByText("The narrator is responding...").length).toBeGreaterThan(0);
    });

    resolveChatRequest?.(
      new Response(JSON.stringify({ error: "The hall failed." }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      })
    );

    await waitFor(() => {
      expect(screen.queryAllByText("The narrator is responding...")).toHaveLength(0);
    });
  });

  it("keeps the opening-scene loading indicator and Shift+Enter newline behavior intact", async () => {
    vi.mocked(useSession).mockReturnValue({
      data: {
        user: { name: "Player One", email: "player@example.com", image: null },
        expires: "2099-01-01T00:00:00.000Z",
      },
      status: "authenticated",
      update: vi.fn(),
    });

    let resolveCampaignRequest: ((value: Response) => void) | undefined;
    const campaignRequest = new Promise<Response>((resolve) => {
      resolveCampaignRequest = resolve;
    });

    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === "/api/campaigns") {
        return Promise.resolve(
          new Response(JSON.stringify([]), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        );
      }

      if (String(input) === "/api/campaign") {
        return campaignRequest;
      }

      return Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );
    });

    render(<Home />);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith("/api/campaigns");
    });

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith("/api/campaign", expect.anything());
    });

    expect(screen.getAllByText("Loading opening...").length).toBeGreaterThan(0);

    const onSend = vi.fn();
    const onChange = vi.fn();
    const { rerender } = render(
      <ChatInput value="line one" onChange={onChange} onSend={onSend} sendDisabled={true} />
    );

    const textarea = screen.getAllByRole("textbox").at(-1) as HTMLTextAreaElement;
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true, code: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.keyDown(textarea, { key: "Enter", code: "Enter" });
    expect(textarea).toHaveValue("line one");

    rerender(
      <ChatInput value="line one" onChange={onChange} onSend={onSend} sendDisabled={false} />
    );
    fireEvent.keyDown(screen.getAllByRole("textbox").at(-1) as HTMLTextAreaElement, {
      key: "Enter",
      shiftKey: true,
      code: "Enter",
    });
    expect(onSend).not.toHaveBeenCalled();

    resolveCampaignRequest?.(
      new Response(JSON.stringify({
        campaign_id: "campaign-123",
        name: "The Lost Crypt",
        description: null,
        messages: [],
        truncated: false,
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
  });

  it("keeps a 429 failure on the player message and retries without changing the draft", async () => {
    vi.mocked(useSession).mockReturnValue({
      data: { user: { name: "Player One", email: "player@example.com", image: null }, expires: "2099-01-01T00:00:00.000Z" },
      status: "authenticated",
      update: vi.fn(),
    });

    let chatCalls = 0;
    let resolveFirstChat: ((value: Response) => void) | undefined;
    const firstChat = new Promise<Response>((resolve) => { resolveFirstChat = resolve; });
    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === "/api/campaigns") {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (String(input) === "/api/campaign") {
        return Promise.resolve(new Response(JSON.stringify({ campaign_id: "campaign-123", name: "The Lost Crypt", description: null, messages: [], truncated: false }), { status: 200 }));
      }
      if (String(input) === "/api/chat") {
        chatCalls += 1;
        return chatCalls === 1
          ? firstChat
          : chatCalls === 2
            ? Promise.resolve(new Response(JSON.stringify({ error: "rate limited again", code: "temporary_rate_limit", retryable: true }), { status: 429 }))
            : Promise.resolve(new Response(JSON.stringify({ reply: "The hall answers." }), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }));
      }
      return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }));
    });

    render(<Home />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith("/api/campaign", expect.anything()));
    const textarea = await screen.findByRole("textbox", { name: "Enter your command" });
    fireEvent.change(textarea, { target: { value: "search behind the bookshelf" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    fireEvent.change(textarea, { target: { value: "go north" } });

    resolveFirstChat?.(new Response(JSON.stringify({ error: "rate limited", code: "temporary_rate_limit", retryable: true }), { status: 429 }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Retry sending/ })).toBeEnabled());
    expect(screen.getAllByText("search behind the bookshelf")).toHaveLength(2);
    expect(screen.queryByText("The narrator is responding...")).not.toBeInTheDocument();
    expect(textarea).toHaveValue("go north");

    fireEvent.click(screen.getByRole("button", { name: /Retry sending/ }));
    expect(textarea).toHaveValue("go north");
    await waitFor(() => expect(chatCalls).toBe(2));
    await waitFor(() => expect(screen.getByRole("button", { name: /Retry sending/ })).toBeEnabled());
    expect(screen.getAllByText("search behind the bookshelf")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: /Retry sending/ }));
    await waitFor(() => expect(chatCalls).toBe(3));
    await waitFor(() => expect(screen.queryByRole("button", { name: /Retry sending/ })).not.toBeInTheDocument());
    expect(screen.getAllByText("search behind the bookshelf")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /Retry sending/ })).not.toBeInTheDocument();
    expect(chatCalls).toBe(3);
    const chatRequestCalls = vi.mocked(global.fetch).mock.calls.filter(([input]) => String(input) === "/api/chat");
    expect(chatRequestCalls[1]?.[1]).toEqual(expect.objectContaining({
      body: expect.stringContaining('"message":"search behind the bookshelf"'),
    }));
  });

  it("marks network and server failures as ambiguous with Retry when the logical send carries a stable idempotency key", async () => {
    vi.mocked(useSession).mockReturnValue({
      data: { user: { name: "Player One", email: "player@example.com", image: null }, expires: "2099-01-01T00:00:00.000Z" },
      status: "authenticated",
      update: vi.fn(),
    });

    let chatCalls = 0;
    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === "/api/campaigns") return Promise.resolve(new Response("[]", { status: 200 }));
      if (String(input) === "/api/campaign") return Promise.resolve(new Response(JSON.stringify({ campaign_id: "campaign-123", name: "The Lost Crypt", description: null, messages: [], truncated: false }), { status: 200 }));
      if (String(input) === "/api/chat") {
        chatCalls += 1;
        return chatCalls === 1
          ? Promise.reject(new Error("connection lost"))
          : Promise.resolve(new Response(JSON.stringify({ error: "bad request" }), { status: 400 }));
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });

    render(<Home />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith("/api/campaign", expect.anything()));
    const textarea = await screen.findByRole("textbox", { name: "Enter your command" });
    fireEvent.change(textarea, { target: { value: "open the iron door" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByText(AMBIGUOUS_RETRY_MESSAGE)).toBeInTheDocument());
    expect(screen.getAllByText("open the iron door")).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: /Retry sending/ }).length).toBeGreaterThan(0);
    expect(screen.queryByText("The narrator is responding...")).not.toBeInTheDocument();
  });

  it.each([
    ["daily token limit", "daily_token_limit", "Daily limit reached", "You've reached today's token limit", "2026-08-26T00:00:00Z"],
    ["daily request limit", "daily_request_limit", "Daily limit reached", "You've reached today's request limit", "2026-08-26T00:00:00Z"],
    ["campaign turn limit", "campaign_turn_limit", "Campaign limit reached", "This campaign has reached its maximum number of turns.", undefined],
    ["maximum campaigns", "max_campaigns", "Campaign limit reached", "You've reached the maximum number of campaigns.", undefined],
  ])("renders %s without retry", async (_label, code, title, message, retryAt) => {
    vi.mocked(useSession).mockReturnValue({
      data: { user: { name: "Player One", email: "player@example.com", image: null }, expires: "2099-01-01T00:00:00.000Z" },
      status: "authenticated",
      update: vi.fn(),
    });

    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === "/api/campaigns") return Promise.resolve(new Response("[]", { status: 200 }));
      if (String(input) === "/api/campaign") return Promise.resolve(new Response(JSON.stringify({ campaign_id: "campaign-123", name: "The Lost Crypt", description: null, messages: [], truncated: false }), { status: 200 }));
      if (String(input) === "/api/chat") {
        return Promise.resolve(new Response(JSON.stringify({
          error: message,
          code,
          retryable: false,
          ...(retryAt ? { retry_at: retryAt } : {}),
        }), { status: 429 }));
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });

    render(<Home />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith("/api/campaign", expect.anything()));
    const textarea = await screen.findByRole("textbox", { name: "Enter your command" });
    fireEvent.change(textarea, { target: { value: "test command" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByText(title)).toBeInTheDocument());
    expect(
      screen.getByText(
        code === "daily_token_limit"
          ? /You've used today's token allowance\./
          : code === "daily_request_limit"
            ? /You've used today's request allowance\./
            : message
      )
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Retry sending/ })).not.toBeInTheDocument();
    if (retryAt) {
      expect(screen.getByText(/You can continue (after|tomorrow at)/)).toBeInTheDocument();
    }
  });

  it("generates a stable UUID per logical send and a different UUID for the next identical send", async () => {
    vi.mocked(useSession).mockReturnValue({
      data: { user: { name: "Player One", email: "player@example.com", image: null }, expires: "2099-01-01T00:00:00.000Z" },
      status: "authenticated",
      update: vi.fn(),
    });

    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === "/api/campaigns") {
        return Promise.resolve(new Response("[]", { status: 200 }));
      }
      if (String(input) === "/api/campaign") {
        return Promise.resolve(new Response(JSON.stringify({
          campaign_id: "campaign-123",
          name: "The Lost Crypt",
          description: null,
          messages: [{ turn_id: "turn-42", role: "assistant", content: "A previous turn", created_at: "2026-01-01T00:00:00Z" }],
          truncated: false,
        }), { status: 200 }));
      }
      if (String(input) === "/api/chat") {
        return Promise.resolve(new Response(JSON.stringify({ reply: "The hall answers.", campaign_id: "campaign-123", turn_id: "turn-99" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }));
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });

    render(<Home />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith("/api/campaign", expect.anything()));
    const textarea = await screen.findByRole("textbox", { name: "Enter your command" });

    expect(screen.getAllByText("A previous turn").length).toBeGreaterThan(0);

    fireEvent.change(textarea, { target: { value: "look around" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(vi.mocked(global.fetch).mock.calls.filter(([input]) => String(input) === "/api/chat")).toHaveLength(1);
    });

    const firstInit = vi.mocked(global.fetch).mock.calls.find(([input]) => String(input) === "/api/chat")?.[1] as RequestInit | undefined;
    const firstIdempotencyKey = new Headers(firstInit?.headers as HeadersInit | undefined).get("Idempotency-Key");
    expect(firstIdempotencyKey).toMatch(UUID_V4_PATTERN);

    await waitFor(() => expect(screen.getAllByText("The hall answers.").length).toBeGreaterThan(0));

    fireEvent.change(textarea, { target: { value: "look around" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(vi.mocked(global.fetch).mock.calls.filter(([input]) => String(input) === "/api/chat")).toHaveLength(2);
    });

    const secondInit = vi.mocked(global.fetch).mock.calls.filter(([input]) => String(input) === "/api/chat")[1]?.[1] as RequestInit | undefined;
    const secondIdempotencyKey = new Headers(secondInit?.headers as HeadersInit | undefined).get("Idempotency-Key");
    expect(secondIdempotencyKey).toMatch(UUID_V4_PATTERN);
    expect(secondIdempotencyKey).not.toBe(firstIdempotencyKey);
  });

  it("uses strong runtime randomness to generate a valid UUIDv4 when randomUUID is unavailable", async () => {
    vi.mocked(useSession).mockReturnValue({
      data: { user: { name: "Player One", email: "player@example.com", image: null }, expires: "2099-01-01T00:00:00.000Z" },
      status: "authenticated",
      update: vi.fn(),
    });

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
        return Promise.resolve(new Response(JSON.stringify({ reply: "The hall answers.", campaign_id: "campaign-123", turn_id: "turn-99" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }));
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });

    const cryptoSource = globalThis.crypto;
    const originalRandomUUID = cryptoSource.randomUUID;
    const originalGetRandomValues = cryptoSource.getRandomValues.bind(cryptoSource);
    const getRandomValues = vi.fn((array: Uint8Array) => {
      array.set([0, 1, 2, 3, 4, 5, 6, 7, 200, 9, 10, 11, 12, 13, 14, 15]);
      return array;
    });
    Object.defineProperty(cryptoSource, "randomUUID", { configurable: true, value: undefined });
    Object.defineProperty(cryptoSource, "getRandomValues", { configurable: true, value: getRandomValues });

    try {
      render(<Home />);
      await waitFor(() => expect(global.fetch).toHaveBeenCalledWith("/api/campaign", expect.anything()));
      const textarea = await screen.findByRole("textbox", { name: "Enter your command" });
      fireEvent.change(textarea, { target: { value: "look around" } });
      fireEvent.click(screen.getByRole("button", { name: "Send" }));

      await waitFor(() => {
        expect(vi.mocked(global.fetch).mock.calls.filter(([input]) => String(input) === "/api/chat")).toHaveLength(1);
      });

      const init = vi.mocked(global.fetch).mock.calls.find(([input]) => String(input) === "/api/chat")?.[1] as RequestInit | undefined;
      const idempotencyKey = new Headers(init?.headers as HeadersInit | undefined).get("Idempotency-Key");
      expect(idempotencyKey).toBe("00010203-0405-4607-8809-0a0b0c0d0e0f");
      expect(idempotencyKey).toMatch(UUID_V4_PATTERN);
      expect(getRandomValues).toHaveBeenCalledTimes(1);
    } finally {
      Object.defineProperty(cryptoSource, "randomUUID", { configurable: true, value: originalRandomUUID });
      Object.defineProperty(cryptoSource, "getRandomValues", { configurable: true, value: originalGetRandomValues });
    }
  });

  it("reuses the same idempotency key on Retry for ambiguous 5xx failures", async () => {
    vi.mocked(useSession).mockReturnValue({
      data: { user: { name: "Player One", email: "player@example.com", image: null }, expires: "2099-01-01T00:00:00.000Z" },
      status: "authenticated",
      update: vi.fn(),
    });

    let chatAttempts = 0;
    let resolveFirstChat: ((value: Response) => void) | undefined;
    const firstChat = new Promise<Response>((resolve) => { resolveFirstChat = resolve; });

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
        if (chatAttempts === 1) {
          return firstChat;
        }
        return Promise.resolve(new Response(JSON.stringify({ error: "The hall failed." }), { status: 500 }));
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });

    render(<Home />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith("/api/campaign", expect.anything()));
    const textarea = await screen.findByRole("textbox", { name: "Enter your command" });
    fireEvent.change(textarea, { target: { value: "open the iron door" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    resolveFirstChat?.(new Response(JSON.stringify({ error: "The hall failed." }), { status: 500 }));
    await waitFor(() => expect(screen.getByText(AMBIGUOUS_RETRY_MESSAGE)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Retry sending/ })).toBeEnabled();

    const firstFailedRequest = vi.mocked(global.fetch).mock.calls.find(([input]) => String(input) === "/api/chat")?.[1] as RequestInit | undefined;
    const firstKey = new Headers(firstFailedRequest?.headers as HeadersInit | undefined).get("Idempotency-Key");

    fireEvent.click(screen.getByRole("button", { name: /Retry sending/ }));
    await waitFor(() => expect(chatAttempts).toBe(2));

    const retryRequest = vi.mocked(global.fetch).mock.calls.filter(([input]) => String(input) === "/api/chat").at(-1)?.[1] as RequestInit | undefined;
    const retryKey = new Headers(retryRequest?.headers as HeadersInit | undefined).get("Idempotency-Key");
    expect(retryKey).toBe(firstKey);
    expect(screen.getByRole("button", { name: /Retry sending/ })).toBeEnabled();
  });

  it("uses a safe fallback for a malformed daily limit reset and does not retry an unknown 429", async () => {
    vi.mocked(useSession).mockReturnValue({
      data: { user: { name: "Player One", email: "player@example.com", image: null }, expires: "2099-01-01T00:00:00.000Z" },
      status: "authenticated",
      update: vi.fn(),
    });

    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === "/api/campaigns") return Promise.resolve(new Response("[]", { status: 200 }));
      if (String(input) === "/api/campaign") return Promise.resolve(new Response(JSON.stringify({ campaign_id: "campaign-123", name: "The Lost Crypt", description: null, messages: [], truncated: false }), { status: 200 }));
      if (String(input) === "/api/chat") return Promise.resolve(new Response(JSON.stringify({ error: "unknown limit" }), { status: 429 }));
      return Promise.resolve(new Response("{}", { status: 200 }));
    });

    render(<Home />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith("/api/campaign", expect.anything()));
    const textarea = await screen.findByRole("textbox", { name: "Enter your command" });
    fireEvent.change(textarea, { target: { value: "test command" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByText("unknown limit")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /Retry sending/ })).not.toBeInTheDocument();
  });
});
