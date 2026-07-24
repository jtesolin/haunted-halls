import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Home from "@/app/page";
import { signIn, signOut, useSession } from "next-auth/react";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn(),
  SessionProvider: ({ children }: { children: ReactNode }) => children,
}));

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
      expect(global.fetch).toHaveBeenCalledWith("/api/campaigns/player-1");
    });

    expect(screen.getAllByText("player@example.com").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
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
});
