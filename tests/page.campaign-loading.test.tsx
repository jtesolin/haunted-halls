import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSession } from "next-auth/react";
import Home from "@/app/page";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(),
  signIn: vi.fn(),
  getProviders: vi.fn(),
  signOut: vi.fn(),
  SessionProvider: ({ children }: { children: ReactNode }) => children,
}));

type Deferred = { promise: Promise<Response>; resolve: (response: Response) => void };

function deferred(): Deferred {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

function campaign(id: string, text: string) {
  return {
    campaign_id: id,
    name: `Campaign ${id}`,
    description: null,
    truncated: false,
    messages: [{ turn_id: `${id}-t1`, role: "assistant", content: text, created_at: "2026-01-01T00:00:00Z" }],
  };
}

const summaries = [
  { campaign_id: "a", name: "Campaign a", last_message: "a-last" },
  { campaign_id: "b", name: "Campaign b", last_message: "b-last" },
];

function signedIn() {
  vi.mocked(useSession).mockReturnValue({
    data: { user: { name: "Player", email: "p@example.com", image: null }, expires: "2099-01-01T00:00:00.000Z" },
    status: "authenticated",
    update: vi.fn(),
  });
}

function calls(path: string, method = "GET") {
  return vi
    .mocked(global.fetch)
    .mock.calls.filter(([input, init]) => String(input) === path && (init?.method ?? "GET") === method);
}

const composer = () => screen.getByRole("textbox", { name: "Enter your command" });

describe("campaign loading failures", () => {
  beforeEach(() => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    vi.mocked(useSession).mockReset();
    window.history.replaceState({}, "", "/");
    signedIn();
  });

  it.each([
    ["a non-OK response", () => Promise.resolve(json({ error: "down" }, 502))],
    ["a network error", () => Promise.reject(new TypeError("network down"))],
  ])("shows an actionable error and creates no campaign when the list fails with %s", async (_label, listResponse) => {
    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) =>
      String(input) === "/api/campaigns" ? listResponse() : Promise.resolve(json({}))
    );

    render(<Home />);

    expect(await screen.findByText("Your campaigns could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByText(/Your adventure begins/)).not.toBeInTheDocument();
    expect(composer()).toBeDisabled();
    expect(calls("/api/campaign", "POST")).toHaveLength(0);
    expect(calls("/api/chat", "POST")).toHaveLength(0);
  });

  it("retries the campaign list on request and recovers without creating a campaign", async () => {
    let listCalls = 0;
    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/campaigns") {
        listCalls += 1;
        return Promise.resolve(listCalls === 1 ? json({}, 502) : json(summaries));
      }
      if (url === "/api/campaign/a") return Promise.resolve(json(campaign("a", "Welcome back")));
      return Promise.resolve(json({}));
    });

    render(<Home />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Welcome back")).toBeInTheDocument();
    expect(composer()).toBeEnabled();
    expect(listCalls).toBe(2);
    expect(calls("/api/campaign", "POST")).toHaveLength(0);
  });

  it("shows a history error instead of an empty adventure and locks the composer", async () => {
    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/campaigns") return Promise.resolve(json(summaries));
      if (url === "/api/campaign/a") return Promise.resolve(json({ error: "down" }, 502));
      return Promise.resolve(json({}));
    });

    render(<Home />);

    expect(await screen.findByText("This campaign's history could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByText(/Your adventure begins/)).not.toBeInTheDocument();
    expect(composer()).toBeDisabled();
    expect(calls("/api/chat", "POST")).toHaveLength(0);
    expect(calls("/api/campaign", "POST")).toHaveLength(0);
  });

  it("retries a failed history load and then enables the composer", async () => {
    let historyCalls = 0;
    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/campaigns") return Promise.resolve(json(summaries));
      if (url === "/api/campaign/a") {
        historyCalls += 1;
        return Promise.reject(historyCalls === 1 ? new TypeError("network down") : undefined).catch((e) => {
          if (e) throw e;
          return json(campaign("a", "Recovered history"));
        });
      }
      return Promise.resolve(json({}));
    });

    render(<Home />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Recovered history")).toBeInTheDocument();
    expect(composer()).toBeEnabled();
    expect(historyCalls).toBe(2);
  });
});

describe("campaign history races", () => {
  beforeEach(() => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    vi.mocked(useSession).mockReset();
    window.history.replaceState({}, "", "/");
    signedIn();
  });

  it("keeps the composer locked while history loads, so nothing can be sent into an unloaded campaign", async () => {
    const history = deferred();
    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/campaigns") return Promise.resolve(json(summaries));
      if (url === "/api/campaign/a") return history.promise;
      return Promise.resolve(json({}));
    });

    render(<Home />);

    expect(await screen.findByText("Loading campaign history...")).toBeInTheDocument();
    expect(composer()).toBeDisabled();
    expect(calls("/api/campaign/a")).toHaveLength(1);

    history.resolve(json(campaign("a", "Loaded")));
    expect(await screen.findByText("Loaded")).toBeInTheDocument();
    expect(composer()).toBeEnabled();
  });

  it("does not issue a duplicate history request when the loading campaign is selected again", async () => {
    const history = deferred();
    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/campaigns") return Promise.resolve(json(summaries));
      if (url === "/api/campaign/a") return history.promise;
      return Promise.resolve(json({}));
    });

    render(<Home />);
    await screen.findByText("Loading campaign history...");
    fireEvent.click(screen.getAllByText("Campaign a")[0]);

    expect(calls("/api/campaign/a")).toHaveLength(1);
    history.resolve(json(campaign("a", "Loaded")));
    await screen.findByText("Loaded");
  });

  it("applies a late history response only to its own campaign and never over a pending or failed message in another", async () => {
    const historyA = deferred();
    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/campaigns") return Promise.resolve(json(summaries));
      if (url === "/api/campaign/a") return historyA.promise;
      if (url === "/api/campaign/b") return Promise.resolve(json(campaign("b", "B history")));
      if (url === "/api/chat") return Promise.reject(new TypeError("network down"));
      return Promise.resolve(json({}));
    });

    render(<Home />);
    await screen.findByText("Loading campaign history...");

    // Switch to B while A's history request is still in flight.
    fireEvent.click(screen.getAllByText("Campaign b")[0]);
    expect(await screen.findByText("B history")).toBeInTheDocument();

    // Send in B; the chat request fails, leaving a failed (retryable) local message.
    fireEvent.change(composer(), { target: { value: "open the door" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();

    // A's stale response now arrives. B must be untouched.
    historyA.resolve(json(campaign("a", "A history")));
    await waitFor(() => expect(calls("/api/campaign/a")).toHaveLength(1));
    await act(async () => {
      await historyA.promise;
    });

    expect(screen.queryByText("A history")).not.toBeInTheDocument();
    expect(screen.getAllByText("open the door").length).toBeGreaterThan(0);
    expect(screen.getByText("B history")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();

    // A still loaded correctly in the background: selecting it shows its own history
    // without another request.
    fireEvent.click(screen.getAllByText("Campaign a")[0]);
    expect(await screen.findByText("A history")).toBeInTheDocument();
    expect(calls("/api/campaign/a")).toHaveLength(1);
  });
});

describe("campaign history in-flight guards", () => {
  beforeEach(() => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    vi.mocked(useSession).mockReset();
    window.history.replaceState({}, "", "/");
  });

  it("does not start a second history request when the campaign is re-activated while its load is in flight", async () => {
    signedIn();
    const historyA = deferred();
    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/campaigns") return Promise.resolve(json(summaries));
      if (url === "/api/campaign/a") return historyA.promise;
      if (url === "/api/campaign/b") return Promise.resolve(json(campaign("b", "B history")));
      return Promise.resolve(json({}));
    });

    render(<Home />);
    await screen.findByText("Loading campaign history...");
    fireEvent.click(screen.getAllByText("Campaign b")[0]);
    await screen.findByText("B history");

    // Re-activating A re-runs the loader effect while A's first request is still pending.
    fireEvent.click(screen.getAllByText("Campaign a")[0]);
    await screen.findByText("Loading campaign history...");
    await act(async () => {});

    expect(calls("/api/campaign/a")).toHaveLength(1);
    historyA.resolve(json(campaign("a", "A history")));
    expect(await screen.findByText("A history")).toBeInTheDocument();
  });

  it("drops a history response that resolves after the signed-in user changed", async () => {
    const asUser = (internalUserId: string) =>
      vi.mocked(useSession).mockReturnValue({
        data: {
          user: { name: "Player", email: `${internalUserId}@example.com`, image: null },
          internalUserId,
          expires: "2099-01-01T00:00:00.000Z",
        },
        status: "authenticated",
        update: vi.fn(),
      } as never);

    const staleHistory = deferred();
    const freshHistory = deferred();
    let historyCalls = 0;
    vi.mocked(global.fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/campaigns") return Promise.resolve(json(summaries));
      if (url === "/api/campaign/a") {
        historyCalls += 1;
        return historyCalls === 1 ? staleHistory.promise : freshHistory.promise;
      }
      return Promise.resolve(json({}));
    });

    asUser("user-1");
    const view = render(<Home />);
    await waitFor(() => expect(historyCalls).toBe(1));

    // A different user signs in while user-1's history request is still in flight. The
    // new user's session list contains a campaign with the same id.
    asUser("user-2");
    view.rerender(<Home />);
    await waitFor(() => expect(historyCalls).toBe(2));

    staleHistory.resolve(json(campaign("a", "STALE user-1 history")));
    await act(async () => {
      await staleHistory.promise;
    });
    expect(screen.queryByText("STALE user-1 history")).not.toBeInTheDocument();
    expect(composer()).toBeDisabled();

    freshHistory.resolve(json(campaign("a", "FRESH user-2 history")));
    expect(await screen.findByText("FRESH user-2 history")).toBeInTheDocument();
    expect(screen.queryByText("STALE user-1 history")).not.toBeInTheDocument();
  });
});
