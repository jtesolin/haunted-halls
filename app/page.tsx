"use client";

import Image from "next/image";
import { useCallback, useEffect, useMemo, useState, useTransition, type CSSProperties } from "react";
import { signIn, signOut, useSession } from "next-auth/react";
import ChatInput from "@/components/ChatInput";
import CampaignSidebar from "@/components/CampaignSidebar";
import CampaignToolbar from "@/components/CampaignToolbar";
import ConversationView from "@/components/ConversationView";
import type {
  CampaignDetailsResponse,
  CampaignSummary,
  ChatMessage,
  ChatSession,
  CreateCampaignResponse,
  ChatFailure,
} from "@/types/chat";

const MAX_INPUT_CHARACTERS = 2000;
const OPENING_LOADING_TEXT = "Loading opening...";
const NARRATOR_LOADING_TEXT = "The narrator is responding...";
const SIDEBAR_PREF_KEY = "haunted-halls-sidebar-collapsed";
const SIDEBAR_WIDTH = "320px";
const COLLAPSED_TOOLBAR_WIDTH = "64px";
const MOBILE_BREAKPOINT_QUERY = "(max-width: 767px)";
const GENERIC_SIGN_IN_ERROR = "Sign-in failed. Please try again.";

function getSafeCallbackPath(candidate: string): string {
  if (typeof window === "undefined") {
    return "/";
  }

  try {
    const current = new URL(window.location.href);
    const target = new URL(candidate, current.origin);

    if (target.origin !== current.origin) {
      return "/";
    }

    return `${target.pathname}${target.search}${target.hash}`;
  } catch {
    return "/";
  }
}

function getUserFacingErrorMessage(status: number, fallback: string) {
  switch (status) {
    case 401:
      return "You must sign in before sending commands.";
    case 400:
      return "The message could not be sent. It may be empty, too long, or the campaign is no longer active.";
    case 404:
      return "The requested campaign or character could not be found.";
    case 422:
      return "The request could not be completed. Please try again.";
    case 429:
      return "The hall is rate limiting requests right now. Please wait a moment and try again.";
    case 502:
      return "Delivery could not be confirmed. This action cannot be safely retried yet.";
    default:
      return fallback;
  }
}

function createChatFailure(
  message: string,
  category: ChatFailure["category"],
  retryable: boolean,
  details: Pick<ChatFailure, "title" | "code" | "retry_at"> = {}
): ChatFailure {
  return { message, category, retryable, ...details };
}

function formatLimitResetTime(retryAt: string | undefined, fallback: string): string {
  if (!retryAt) {
    return fallback;
  }

  const reset = new Date(retryAt);
  if (Number.isNaN(reset.getTime())) {
    return fallback;
  }

  const time = new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(reset);
  const now = new Date();
  const resetDate = `${reset.getFullYear()}-${reset.getMonth()}-${reset.getDate()}`;
  const today = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}`;
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  const tomorrowDate = `${tomorrow.getFullYear()}-${tomorrow.getMonth()}-${tomorrow.getDate()}`;

  if (resetDate === today) {
    return `You can continue after ${time}.`;
  }
  if (resetDate === tomorrowDate) {
    return `You can continue tomorrow at ${time}.`;
  }

  const date = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(reset);
  return `You can continue after ${date} at ${time}.`;
}

function formatDailyLimitMessage(retryAt: string | undefined, allowance: string, fallback: string): string {
  const resetMessage = formatLimitResetTime(retryAt, fallback);
  return resetMessage === fallback
    ? fallback
    : `You've used today's ${allowance} allowance. ${resetMessage}`;
}

function getChatFailure(status: number, payload: unknown): ChatFailure {
  const response = payload && typeof payload === "object" ? payload as Record<string, unknown> : {};
  const code = typeof response.code === "string" ? response.code : undefined;
  const retryAt = typeof response.retry_at === "string" ? response.retry_at : undefined;
  const serverMessage = typeof response.error === "string" ? response.error : undefined;

  switch (code) {
    case "daily_token_limit":
      return createChatFailure(
        formatDailyLimitMessage(
          retryAt,
          "token",
          "You've reached today's token limit. Please try again after the daily limit resets."
        ),
        "rejected",
        false,
        { title: "Daily limit reached", code, retry_at: retryAt }
      );
    case "daily_request_limit":
      return createChatFailure(
        formatDailyLimitMessage(
          retryAt,
          "request",
          "You've reached today's request limit. Please try again after the daily limit resets."
        ),
        "rejected",
        false,
        { title: "Daily limit reached", code, retry_at: retryAt }
      );
    case "campaign_turn_limit":
      return createChatFailure(
        "This campaign has reached its maximum number of turns.",
        "rejected",
        false,
        { title: "Campaign limit reached", code }
      );
    case "max_campaigns":
      return createChatFailure(
        "You've reached the maximum number of campaigns.",
        "rejected",
        false,
        { title: "Campaign limit reached", code }
      );
    default: {
      const explicitRetryable = response.retryable === true && Boolean(code);
      const fallbackMessage = status === 429
        ? serverMessage ?? "The request was rejected. Please try again later."
        : getUserFacingErrorMessage(status, serverMessage ?? "The hall did not respond.");
      return createChatFailure(
        fallbackMessage,
        "rejected",
        explicitRetryable,
        { code, retry_at: retryAt }
      );
    }
  }
}

function createSession(
  title: string,
  campaignId?: string,
  lastMessage?: string | null
): ChatSession {
  return {
    id: campaignId ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    title,
    campaign_id: campaignId,
    last_message: lastMessage,
    updated_at: Date.now(),
    conversation_loaded: false,
    messages: [],
  };
}

function sortSessionsByRecency(sessionList: ChatSession[]): ChatSession[] {
  return [...sessionList].sort((a, b) => b.updated_at - a.updated_at);
}

function summarizeSessionTitle(message: string): string {
  const compact = message.replace(/\s+/g, " ").trim();
  if (!compact) {
    return "New adventure";
  }

  return compact.length > 40 ? `${compact.slice(0, 37)}...` : compact;
}

function shouldAutonameSession(sessionTitle: string): boolean {
  return sessionTitle === "New adventure" || /^Adventure \d+$/.test(sessionTitle);
}

function createLoadingNarratorMessage(loadingText: string): ChatMessage {
  return {
    id: `loading-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    role: "assistant",
    text: loadingText,
    is_loading: true,
    loading_text: loadingText,
  };
}

export default function Home() {
  const { data: session, status: authStatus } = useSession();
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [messageText, setMessageText] = useState("");
  const [authError, setAuthError] = useState(() => {
    if (typeof window === "undefined") {
      return "";
    }

    const url = new URL(window.location.href);
    return url.searchParams.get("error") ? GENERIC_SIGN_IN_ERROR : "";
  });
  const [requestError, setRequestError] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isCreatingSession, setIsCreatingSession] = useState(false);
  const [deletingSessionIds, setDeletingSessionIds] = useState<string[]>([]);
  const [isDeletingAllSessions, setIsDeletingAllSessions] = useState(false);
  const [isCreatingTransitionPending, startCreateTransition] = useTransition();
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isMobileViewport, setIsMobileViewport] = useState(false);
  const [isMobileDrawerOpen, setIsMobileDrawerOpen] = useState(false);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) ?? sessions[0] ?? null,
    [sessions, activeSessionId]
  );

  const hasMessages = activeSession ? activeSession.messages.length > 0 : false;
  const isSidebarVisible = isMobileViewport ? isMobileDrawerOpen : !isSidebarCollapsed;
  const isAuthLoading = authStatus === "loading";
  const isAuthenticated = authStatus === "authenticated";
  const disableGameActions = isAuthLoading || !isAuthenticated;
  const isInputLocked = disableGameActions || isCreatingSession;
  const isSendDisabled =
    isInputLocked ||
    isSending ||
    messageText.trim().length === 0 ||
    messageText.trim().length > MAX_INPUT_CHARACTERS;
  const inputDisabledPlaceholder = isAuthLoading
    ? "Checking sign-in..."
    : !isAuthenticated
      ? "Sign in to send a command"
      : isCreatingSession
        ? "Preparing campaign..."
        : "Command input unavailable";
  const userDisplayName = session?.user?.name?.trim() || session?.user?.email?.trim() || "Signed in";
  const userEmail = session?.user?.email?.trim() || null;
  const userImage = session?.user?.image?.trim() || null;

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const savedPreference = window.localStorage.getItem(SIDEBAR_PREF_KEY);
    if (savedPreference === "true" || savedPreference === "false") {
      const nextValue = savedPreference === "true";
      queueMicrotask(() => {
        setIsSidebarCollapsed(nextValue);
      });
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const mediaQuery = window.matchMedia(MOBILE_BREAKPOINT_QUERY);
    const handleChange = (event: MediaQueryListEvent) => {
      setIsMobileViewport(event.matches);
      if (!event.matches) {
        setIsMobileDrawerOpen(false);
      }
    };

    queueMicrotask(() => {
      setIsMobileViewport(mediaQuery.matches);
    });

    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", handleChange);
      return () => mediaQuery.removeEventListener("change", handleChange);
    }

    mediaQuery.addListener(handleChange);
    return () => mediaQuery.removeListener(handleChange);
  }, []);

  useEffect(() => {
    if (!isMobileViewport || !isMobileDrawerOpen) {
      return;
    }

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsMobileDrawerOpen(false);
      }
    };

    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [isMobileDrawerOpen, isMobileViewport]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const url = new URL(window.location.href);
    if (!url.searchParams.get("error")) {
      return;
    }

    url.searchParams.delete("error");
    const query = url.searchParams.toString();
    window.history.replaceState({}, "", `${url.pathname}${query ? `?${query}` : ""}${url.hash}`);
  }, []);

  useEffect(() => {
    if (isAuthLoading) {
      return;
    }

    if (!isAuthenticated) {
      queueMicrotask(() => {
        setSessions([]);
        setActiveSessionId("");
        setMessageText("");
        setRequestError("");
        setIsSending(false);
        setIsCreatingSession(false);
        setDeletingSessionIds([]);
        setIsDeletingAllSessions(false);
      });
    }
  }, [isAuthenticated, isAuthLoading]);

  const createAndHydrateSession = useCallback(async () => {
    if (isCreatingSession || !isAuthenticated) {
      return;
    }

    setRequestError("");
    setIsCreatingSession(true);

    const optimisticSessionId = `optimistic-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const loadingNarratorMessage = createLoadingNarratorMessage(OPENING_LOADING_TEXT);
    const optimisticSession: ChatSession = {
      ...createSession("New adventure", optimisticSessionId, OPENING_LOADING_TEXT),
      id: optimisticSessionId,
      title: "New adventure",
      last_message: OPENING_LOADING_TEXT,
      conversation_loaded: true,
      messages: [loadingNarratorMessage],
      is_optimistic: true,
    };

    setSessions((current) => sortSessionsByRecency([optimisticSession, ...current]));
    setActiveSessionId(optimisticSessionId);
    setMessageText("");

    try {
      const response = await fetch("/api/campaign", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });

      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        const userMessage = getUserFacingErrorMessage(
          response.status,
          typeof result?.error === "string" ? result.error : "Unable to create a new campaign."
        );

        setSessions((current) => current.filter((session) => session.id !== optimisticSessionId));
        setActiveSessionId((current) => (current === optimisticSessionId ? "" : current));
        setRequestError(userMessage);
        return;
      }

      const campaign: CreateCampaignResponse = await response.json();
      const fallbackTitle = "New adventure";
      const hydratedMessages = campaign.messages.map((entry) => ({
        id: entry.turn_id,
        role: entry.role,
        text: entry.content,
      }));

      const newestMessage = hydratedMessages[hydratedMessages.length - 1];
      const nextSession: ChatSession = {
        ...createSession(campaign.name || fallbackTitle, campaign.campaign_id),
        title: campaign.name || fallbackTitle,
        messages: hydratedMessages,
        last_message: newestMessage?.text ?? null,
        conversation_loaded: true,
        updated_at: Date.now(),
        is_optimistic: false,
      };

      setSessions((current) =>
        sortSessionsByRecency([
          nextSession,
          ...current.filter(
            (session) => session.id !== optimisticSessionId && session.campaign_id !== campaign.campaign_id
          ),
        ])
      );
      setActiveSessionId(nextSession.id);
      setMessageText("");
    } catch {
      setSessions((current) => current.filter((session) => session.id !== optimisticSessionId));
      setActiveSessionId((current) => (current === optimisticSessionId ? "" : current));
      setRequestError("Unable to create a new campaign right now. Please try again shortly.");
    } finally {
      setIsCreatingSession(false);
    }
  }, [isAuthenticated, isCreatingSession]);

  useEffect(() => {
    if (!isAuthenticated || isAuthLoading) {
      return;
    }

    const loadCampaignSummaries = async () => {
      try {
        const response = await fetch("/api/campaigns");
        if (!response.ok) {
          return;
        }

        const data: CampaignSummary[] = await response.json();
        setSessions((currentSessions) => {
          const now = Date.now();
          const remoteCampaignIds = new Set(data.map((campaign) => campaign.campaign_id));
          const existingRemoteSessions = currentSessions.filter(
            (session) => session.campaign_id && remoteCampaignIds.has(session.campaign_id)
          );
          const remainingSessions = currentSessions.filter(
            (session) => !session.campaign_id || !remoteCampaignIds.has(session.campaign_id)
          );

          const hydratedCampaignSessions = data.map((campaign, index) => {
            const existingSession = existingRemoteSessions.find(
              (session) => session.campaign_id === campaign.campaign_id
            );

            return existingSession
              ? {
                  ...existingSession,
                  title: campaign.name || existingSession.title,
                  last_message: campaign.last_message,
                  updated_at: existingSession.updated_at,
                  conversation_loaded: existingSession.conversation_loaded,
                }
              : {
                  ...createSession(campaign.name, campaign.campaign_id, campaign.last_message),
                  updated_at: now - index,
                };
          });

          const nextSessions = sortSessionsByRecency([...hydratedCampaignSessions, ...remainingSessions]);
          return nextSessions;
        });

        if (data.length === 0) {
          await createAndHydrateSession();
          return;
        }

        const latestCampaign = data[0];
        if (latestCampaign?.campaign_id) {
          void loadCampaignConversation(
            latestCampaign.campaign_id,
            latestCampaign.campaign_id
          );
        }
      } catch {
        // Keep local session flow intact if history cannot be loaded.
        setSessions((currentSessions) =>
          currentSessions.length > 0 ? currentSessions : [createSession("New adventure")]
        );
      }
    };

    void loadCampaignSummaries();
  }, [createAndHydrateSession, isAuthenticated, isAuthLoading]);

  async function loadCampaignConversation(sessionId: string, campaignId: string) {
    try {
      const response = await fetch(`/api/campaign/${encodeURIComponent(campaignId)}`);
      if (!response.ok) {
        return;
      }

      const campaign: CampaignDetailsResponse = await response.json();
      const conversationMessages = [] as ChatMessage[];

      if (campaign.truncated) {
        conversationMessages.push({
          id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
          role: "assistant",
          text: "The memories of the distant past are clouded in mystery",
        });
      }

      campaign.messages.forEach((entry) => {
        conversationMessages.push({
          id: entry.turn_id,
          role: entry.role,
          text: entry.content,
        });
      });

      setSessions((currentSessions) =>
        currentSessions.map((session) =>
          session.id === sessionId
            ? {
                ...session,
                title: campaign.name || session.title,
                messages: conversationMessages,
                updated_at: Date.now(),
                conversation_loaded: true,
              }
            : session
        )
      );
    } catch {
      // Ignore campaign hydration failures and leave the current session intact.
    }
  }

  async function deleteCampaignForPlayer(campaignId: string) {
    const response = await fetch(`/api/campaign/${encodeURIComponent(campaignId)}`, { method: "DELETE" });

    if (!response.ok && response.status !== 404) {
      const result = await response.json().catch(() => ({}));
      const message = getUserFacingErrorMessage(
        response.status,
        typeof result?.error === "string" ? result.error : "Unable to delete campaign."
      );
      throw new Error(message);
    }
  }

  const handleNewSession = () => {
    if (!isAuthenticated) {
      return;
    }

    startCreateTransition(() => {
      void createAndHydrateSession();
    });
  };

  const handleSelectSession = async (id: string) => {
    if (!isAuthenticated) {
      return;
    }

    const selectedSession = sessions.find((session) => session.id === id);
    setActiveSessionId(id);
    setMessageText("");

    if (isMobileViewport) {
      setIsMobileDrawerOpen(false);
    }

    if (!selectedSession?.campaign_id) {
      return;
    }

    if (selectedSession.conversation_loaded) {
      return;
    }

    await loadCampaignConversation(id, selectedSession.campaign_id);
  };

  const handleSidebarToggle = () => {
    if (isMobileViewport) {
      setIsMobileDrawerOpen((current) => !current);
      return;
    }

    setIsSidebarCollapsed((current) => {
      const nextValue = !current;
      window.localStorage.setItem(SIDEBAR_PREF_KEY, String(nextValue));
      return nextValue;
    });
  };

  const handleDeleteSession = async (id: string) => {
    if (isDeletingAllSessions || !isAuthenticated) {
      return;
    }

    const sessionToDelete = sessions.find((session) => session.id === id);
    if (!sessionToDelete || sessionToDelete.is_optimistic) {
      return;
    }

    const shouldDelete = window.confirm(`Delete \"${sessionToDelete.title}\"? This cannot be undone.`);
    if (!shouldDelete) {
      return;
    }

    setRequestError("");
    setDeletingSessionIds((current) => (current.includes(id) ? current : [...current, id]));
    setSessions((current) => current.filter((session) => session.id !== id));
    setActiveSessionId((current) => (current === id ? "" : current));

    try {
      if (sessionToDelete.campaign_id) {
        await deleteCampaignForPlayer(sessionToDelete.campaign_id);
      }
    } catch (error) {
      setSessions((current) => sortSessionsByRecency([sessionToDelete, ...current]));
      setRequestError((error as Error).message);
    } finally {
      setDeletingSessionIds((current) => current.filter((sessionId) => sessionId !== id));
    }
  };

  const handleDeleteAllSessions = async () => {
    if (isDeletingAllSessions || !isAuthenticated) {
      return;
    }

    const deletableSessions = sessions.filter((session) => !session.is_optimistic);
    if (deletableSessions.length === 0) {
      return;
    }

    const shouldDelete = window.confirm("Delete all sessions? This cannot be undone.");
    if (!shouldDelete) {
      return;
    }

    setRequestError("");
    setIsDeletingAllSessions(true);
    setDeletingSessionIds(deletableSessions.map((session) => session.id));

    const failedIds = new Set<string>();

    try {
      await Promise.all(
        deletableSessions.map(async (session) => {
          if (!session.campaign_id) {
            return;
          }

          try {
            await deleteCampaignForPlayer(session.campaign_id);
          } catch {
            failedIds.add(session.id);
          }
        })
      );

      setSessions((current) =>
        current.filter((session) => session.is_optimistic || failedIds.has(session.id))
      );
      setActiveSessionId("");

      if (failedIds.size > 0) {
        setRequestError(
          `Unable to delete ${failedIds.size} session${failedIds.size === 1 ? "" : "s"}. Please try again.`
        );
      }
    } finally {
      setIsDeletingAllSessions(false);
      setDeletingSessionIds([]);
    }
  };

  const sendChatMessage = async ({
    sessionId,
    campaignId,
    messageId,
    text,
    loadingMessageId,
  }: {
    sessionId: string;
    campaignId: string | null;
    messageId: string;
    text: string;
    loadingMessageId: string;
  }) => {
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, campaign_id: campaignId, character_id: null }),
      });

      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        const failure = response.status >= 500
          ? createChatFailure(
              "Delivery could not be confirmed. This action cannot be safely retried yet.",
              "ambiguous",
              false
            )
          : getChatFailure(response.status, result);

        setSessions((currentSessions) =>
          sortSessionsByRecency(
            currentSessions.map((session) =>
              session.id === sessionId
                ? {
                    ...session,
                    last_message: text,
                    updated_at: Date.now(),
                    messages: session.messages
                      .filter((message) => message.id !== loadingMessageId)
                      .map((message) =>
                        message.id === messageId
                          ? { ...message, delivery_state: "failed" as const, failure }
                          : message
                      ),
                  }
                : session
            )
          )
        );
        return;
      }

      const result = await response.json();
      const hallReply = typeof result?.reply === "string" ? result.reply : "The hall did not respond.";
      const returnedCampaignId = typeof result?.campaign_id === "string" ? result.campaign_id : undefined;
      const assistantMessage: ChatMessage = {
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        role: "assistant",
        text: hallReply,
      };

      setSessions((currentSessions) =>
        sortSessionsByRecency(
          currentSessions.map((session) =>
            session.id === sessionId
              ? {
                  ...session,
                  campaign_id: session.campaign_id ?? returnedCampaignId,
                  last_message: hallReply,
                  updated_at: Date.now(),
                  conversation_loaded: true,
                  messages: session.messages
                    .filter((message) => message.id !== loadingMessageId)
                    .map((message) =>
                      message.id === messageId
                        ? { ...message, delivery_state: undefined, failure: undefined }
                        : message
                    )
                    .concat(assistantMessage),
                }
              : session
          )
        )
      );
    } catch {
      const failure = createChatFailure(
        "Delivery could not be confirmed. This action cannot be safely retried yet.",
        "ambiguous",
        false
      );

      setSessions((currentSessions) =>
        sortSessionsByRecency(
          currentSessions.map((session) =>
            session.id === sessionId
              ? {
                  ...session,
                  last_message: text,
                  updated_at: Date.now(),
                  messages: session.messages
                    .filter((message) => message.id !== loadingMessageId)
                    .map((message) =>
                      message.id === messageId
                        ? { ...message, delivery_state: "failed" as const, failure }
                        : message
                    ),
                }
              : session
          )
        )
      );
    } finally {
      setIsSending(false);
    }
  };

  const handleSendMessage = () => {
    const trimmed = messageText.trim();

    if (!trimmed || isSending || !activeSession || !isAuthenticated) {
      return;
    }

    if (trimmed.length > MAX_INPUT_CHARACTERS) {
      setRequestError(`Please keep your message under ${MAX_INPUT_CHARACTERS} characters.`);
      return;
    }

    const sessionId = activeSession.id;
    const campaignId = activeSession.campaign_id ?? null;
    const userMessage: ChatMessage = {
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      role: "user",
      text: trimmed,
      delivery_state: "pending",
    };
    const loadingNarratorMessage = createLoadingNarratorMessage(NARRATOR_LOADING_TEXT);

    setRequestError("");
    setMessageText("");
    setIsSending(true);
    setSessions((currentSessions) =>
      sortSessionsByRecency(
        currentSessions.map((session) => {
          if (session.id !== sessionId) {
            return session;
          }

          const nextTitle =
            session.messages.length === 0 && shouldAutonameSession(session.title)
              ? summarizeSessionTitle(trimmed)
              : session.title;

          return {
            ...session,
            title: nextTitle,
            last_message: trimmed,
            updated_at: Date.now(),
            conversation_loaded: true,
            messages: [...session.messages, userMessage, loadingNarratorMessage],
          };
        })
      )
    );

    void sendChatMessage({
      sessionId,
      campaignId,
      messageId: userMessage.id,
      text: trimmed,
      loadingMessageId: loadingNarratorMessage.id,
    });
  };

  const handleRetryMessage = (messageId: string) => {
    if (isSending || !activeSession || !isAuthenticated) {
      return;
    }

    const failedMessage = activeSession.messages.find(
      (message) => message.id === messageId && message.role === "user" && message.failure?.retryable
    );
    if (!failedMessage) {
      return;
    }

    const sessionId = activeSession.id;
    const campaignId = activeSession.campaign_id ?? null;
    const loadingNarratorMessage = createLoadingNarratorMessage(NARRATOR_LOADING_TEXT);

    setRequestError("");
    setIsSending(true);
    setSessions((currentSessions) =>
      currentSessions.map((session) =>
        session.id === sessionId
          ? {
              ...session,
              messages: [
                ...session.messages.map((message) =>
                  message.id === messageId
                    ? { ...message, delivery_state: "pending" as const, failure: undefined }
                    : message
                ),
                loadingNarratorMessage,
              ],
            }
          : session
      )
    );

    void sendChatMessage({
      sessionId,
      campaignId,
      messageId,
      text: failedMessage.text,
      loadingMessageId: loadingNarratorMessage.id,
    });
  };

  const handleSignIn = async () => {
    setAuthError("");

    try {
      const callbackUrl = getSafeCallbackPath(window.location.href);
      await signIn("google", { callbackUrl });
    } catch {
      setAuthError(GENERIC_SIGN_IN_ERROR);
    }
  };

  const handleSignOut = async () => {
    setAuthError("");
    setRequestError("");

    try {
      await signOut({ callbackUrl: "/" });
    } catch {
      setAuthError("Unable to sign out right now. Please try again.");
    }
  };

  return (
    <div className="h-screen overflow-hidden bg-[#09090c] text-white">
      <div className="h-full w-full px-4 py-6 sm:px-6 lg:px-8">
        <div
          className={`relative h-full md:grid md:min-h-0 md:transition-[grid-template-columns,gap] md:duration-300 md:ease-in-out md:motion-reduce:transition-none ${
            isSidebarCollapsed
              ? "md:grid-cols-[var(--collapsed-toolbar-width)_minmax(0,1fr)]"
              : "md:grid-cols-[var(--sidebar-width)_minmax(0,1fr)]"
          } ${isSidebarCollapsed ? "md:gap-0" : "md:gap-4"}`}
          style={
            {
              "--sidebar-width": SIDEBAR_WIDTH,
              "--collapsed-toolbar-width": COLLAPSED_TOOLBAR_WIDTH,
            } as CSSProperties
          }
        >
          <CampaignToolbar
            isCollapsed={isSidebarCollapsed}
            isMobileViewport={isMobileViewport}
            isSidebarVisible={isSidebarVisible}
            onToggleSidebar={handleSidebarToggle}
            onExpandSidebar={handleSidebarToggle}
            onNewSession={handleNewSession}
            isNewSessionDisabled={
              disableGameActions || isCreatingSession || isCreatingTransitionPending || isDeletingAllSessions
            }
          />

          <button
            type="button"
            aria-label="Close sidebar backdrop"
            onClick={() => setIsMobileDrawerOpen(false)}
            className={`absolute inset-0 z-20 bg-black/45 transition-opacity duration-300 ease-in-out md:hidden motion-reduce:transition-none ${
              isMobileDrawerOpen ? "opacity-100" : "pointer-events-none opacity-0"
            }`}
          />

          <CampaignSidebar
            id="campaign-sidebar"
            sessions={sessions}
            activeSessionId={activeSession?.id ?? ""}
            onSelectSession={handleSelectSession}
            onNewSession={handleNewSession}
            onDeleteSession={handleDeleteSession}
            onDeleteAllSessions={handleDeleteAllSessions}
            isCreating={isCreatingSession || isCreatingTransitionPending}
            isDeletingAll={isDeletingAllSessions}
            deletingSessionIds={deletingSessionIds}
            isActionDisabled={disableGameActions}
            onToggleSidebar={handleSidebarToggle}
            isMobileViewport={isMobileViewport}
            isSidebarVisible={isSidebarVisible}
            className={`min-w-0 overflow-hidden ${
              isSidebarCollapsed ? "md:pointer-events-none" : "md:pointer-events-auto"
            } ${
              isMobileDrawerOpen ? "pointer-events-auto" : "pointer-events-none md:pointer-events-auto"
            } absolute inset-y-0 left-0 z-30 w-[min(var(--sidebar-width),calc(100%-0.5rem))] max-w-none transform-gpu transition-transform duration-300 ease-in-out motion-reduce:transition-none ${
              isMobileDrawerOpen ? "translate-x-0" : "-translate-x-[calc(100%+1rem)]"
            } ${
              isSidebarCollapsed
                ? "md:absolute md:inset-y-0 md:left-0 md:z-30 md:w-[var(--sidebar-width)] md:-translate-x-[calc(100%+1rem)]"
                : "md:relative md:inset-auto md:z-auto md:w-auto md:translate-x-0"
            }`}
            contentClassName={`${
              isSidebarCollapsed ? "md:pointer-events-none md:-translate-x-3 md:opacity-0" : "md:translate-x-0 md:opacity-100"
            }`}
          />

          <main className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden p-6 shadow-2xl shadow-black/20">
            <header className="mb-6 flex items-center justify-between gap-4 rounded-3xl border border-white/10 bg-white/5 p-5">
              <div>
                <p className="text-sm uppercase tracking-[0.28em] text-sky-300/80">Dungeon MUD</p>
                <h1 className="mt-2 text-3xl font-semibold text-white">Chat with the haunted halls</h1>
              </div>
              <div className="w-[18rem] shrink-0">
                <div role="status" aria-live="polite" className="rounded-2xl border border-white/10 bg-black/35 p-3">
                  {isAuthLoading ? (
                    <p className="text-sm text-zinc-300">Checking sign-in...</p>
                  ) : isAuthenticated ? (
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2">
                        {userImage ? (
                          <Image
                            src={userImage}
                            alt="Signed-in profile"
                            width={32}
                            height={32}
                            className="h-8 w-8 rounded-full border border-white/20"
                          />
                        ) : (
                          <div className="flex h-8 w-8 items-center justify-center rounded-full border border-white/20 bg-zinc-800 text-xs text-zinc-300">
                            {userDisplayName.charAt(0).toUpperCase()}
                          </div>
                        )}
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-zinc-100">{userDisplayName}</p>
                          {userEmail ? <p className="truncate text-xs text-zinc-400">{userEmail}</p> : null}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={handleSignOut}
                        className="inline-flex h-8 shrink-0 items-center justify-center rounded-lg border border-white/15 px-2.5 text-xs font-semibold text-zinc-200 transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                        aria-label="Sign out"
                      >
                        Sign out
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm text-zinc-300">Sign in to play</p>
                      <button
                        type="button"
                        onClick={handleSignIn}
                        className="inline-flex h-8 shrink-0 items-center justify-center rounded-lg bg-sky-500 px-3 text-xs font-semibold text-white transition hover:bg-sky-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                        aria-label="Sign in with Google"
                      >
                        Sign in with Google
                      </button>
                    </div>
                  )}
                </div>
                {authError ? <p className="mt-2 text-xs text-rose-400" aria-live="polite">{authError}</p> : null}
                {requestError ? <p className="mt-2 text-xs text-amber-300" aria-live="polite">{requestError}</p> : null}
                <p className="sr-only" aria-live="polite">
                  {isAuthLoading
                    ? "Checking sign-in"
                    : isAuthenticated
                      ? "Signed in"
                      : "Signed out"}
                </p>
              </div>
              <div className="rounded-3xl bg-white/5 px-4 py-3 text-sm text-zinc-300">
                {activeSession ? activeSession.messages.length : 0} message{activeSession?.messages.length === 1 ? "" : "s"}
              </div>
            </header>

            <div className="flex h-full min-h-0 flex-col gap-6">
              <div className="flex-1 min-h-0 overflow-hidden rounded-3xl border border-white/10 bg-black/40 p-4">
                {isAuthLoading ? (
                  <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-zinc-400">
                    <p className="max-w-xl text-lg">Checking sign-in...</p>
                  </div>
                ) : !isAuthenticated ? (
                  <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-zinc-400">
                    <p className="max-w-xl text-lg">Sign in to start or continue a campaign.</p>
                    <p className="text-sm">You must sign in before sending commands.</p>
                  </div>
                ) : hasMessages ? (
                  <ConversationView
                    messages={activeSession?.messages ?? []}
                    onRetry={handleRetryMessage}
                    retryDisabled={isSending}
                  />
                ) : (
                  <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-zinc-400">
                    <p className="max-w-xl text-lg">Your adventure begins when you send the first command.</p>
                    <p className="text-sm">Type something like <span className="rounded-full bg-white/5 px-2 py-1 text-white">look</span> or <span className="rounded-full bg-white/5 px-2 py-1 text-white">go north</span>.</p>
                  </div>
                )}
              </div>

              <div className="mt-2 shrink-0">
                <ChatInput
                  value={messageText}
                  onChange={setMessageText}
                  onSend={handleSendMessage}
                  inputDisabled={isInputLocked}
                  sendDisabled={isSendDisabled}
                  disabledPlaceholder={inputDisabledPlaceholder}
                />
              </div>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
