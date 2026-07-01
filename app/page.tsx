"use client";

import { useCallback, useEffect, useMemo, useState, useTransition } from "react";
import ChatInput from "@/components/ChatInput";
import ConversationView from "@/components/ConversationView";
import SessionHistorySidebar from "@/components/SessionHistorySidebar";
import type {
  CampaignDetailsResponse,
  CampaignSummary,
  ChatMessage,
  ChatSession,
  CreateCampaignResponse,
} from "@/types/chat";

const MAX_INPUT_CHARACTERS = 2000;
const OPENING_LOADING_TEXT = "The narrator is preparing your opening scene...";

function getUserFacingErrorMessage(status: number, fallback: string) {
  switch (status) {
    case 401:
      return "The server rejected the request because the shared API token is missing or invalid.";
    case 400:
      return "The message could not be sent. It may be empty, too long, or the campaign is no longer active.";
    case 404:
      return "The requested campaign or character could not be found for this player.";
    case 422:
      return "Please provide a valid player identifier and try again.";
    case 429:
      return "The hall is rate limiting requests right now. Please wait a moment and try again.";
    case 502:
      return "The AI service is temporarily unavailable. Please try again shortly.";
    default:
      return fallback;
  }
}

function createSession(
  title: string,
  campaignId?: string,
  playerId?: string,
  lastMessage?: string | null
): ChatSession {
  return {
    id: campaignId ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    title,
    campaign_id: campaignId,
    player_id: playerId,
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

function createLoadingNarratorMessage(): ChatMessage {
  return {
    id: `loading-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    role: "assistant",
    text: OPENING_LOADING_TEXT,
    is_loading: true,
  };
}

export default function Home() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [messageText, setMessageText] = useState("");
  const [playerId, setPlayerId] = useState("player-1");
  const [playerIdError, setPlayerIdError] = useState("");
  const [requestError, setRequestError] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isCreatingSession, setIsCreatingSession] = useState(false);
  const [isCreatingTransitionPending, startCreateTransition] = useTransition();

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) ?? sessions[0] ?? null,
    [sessions, activeSessionId]
  );

  const hasMessages = activeSession ? activeSession.messages.length > 0 : false;

  const createAndHydrateSession = useCallback(async () => {
    const normalizedPlayerId = playerId.trim();

    if (isCreatingSession) {
      return;
    }

    if (!normalizedPlayerId || normalizedPlayerId.toLowerCase() === "anonymous") {
      setPlayerIdError("Please enter a real player identifier before creating a campaign.");
      return;
    }

    setPlayerIdError("");
    setRequestError("");
    setIsCreatingSession(true);

    const optimisticSessionId = `optimistic-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const loadingNarratorMessage = createLoadingNarratorMessage();
    const optimisticSession: ChatSession = {
      ...createSession("New adventure", optimisticSessionId, normalizedPlayerId, OPENING_LOADING_TEXT),
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
        body: JSON.stringify({ player_id: normalizedPlayerId }),
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
        ...createSession(campaign.name || fallbackTitle, campaign.campaign_id, campaign.player_id ?? normalizedPlayerId),
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
  }, [isCreatingSession, playerId]);

  useEffect(() => {
    const normalizedPlayerId = playerId.trim();
    if (!normalizedPlayerId || normalizedPlayerId.toLowerCase() === "anonymous") {
      return;
    }

    const loadCampaignSummaries = async () => {
      try {
        const response = await fetch(`/api/campaigns/${encodeURIComponent(normalizedPlayerId)}`);
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
                  player_id: existingSession.player_id ?? normalizedPlayerId,
                  last_message: campaign.last_message,
                  updated_at: existingSession.updated_at,
                  conversation_loaded: existingSession.conversation_loaded,
                }
              : {
                  ...createSession(campaign.name, campaign.campaign_id, normalizedPlayerId, campaign.last_message),
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
            latestCampaign.campaign_id,
            normalizedPlayerId
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
  }, [createAndHydrateSession, playerId]);

  async function loadCampaignConversation(sessionId: string, campaignId: string, currentPlayerId: string) {
    try {
      const response = await fetch(
        `/api/campaign/${encodeURIComponent(campaignId)}?player_id=${encodeURIComponent(currentPlayerId)}`
      );
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
                player_id: campaign.player_id ?? session.player_id,
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

  const handleNewSession = () => {
    startCreateTransition(() => {
      void createAndHydrateSession();
    });
  };

  const handleSelectSession = async (id: string) => {
    const selectedSession = sessions.find((session) => session.id === id);
    setActiveSessionId(id);
    setMessageText("");

    if (!selectedSession?.campaign_id) {
      return;
    }

    if (selectedSession.conversation_loaded) {
      return;
    }

    await loadCampaignConversation(id, selectedSession.campaign_id, playerId.trim());
  };

  const handleSendMessage = async () => {
    const trimmed = messageText.trim();
    const normalizedPlayerId = playerId.trim();

    if (!trimmed || isSending || !activeSession) {
      return;
    }

    if (!normalizedPlayerId || normalizedPlayerId.toLowerCase() === "anonymous") {
      setPlayerIdError("Please enter a real player identifier before sending.");
      return;
    }

    if (trimmed.length > MAX_INPUT_CHARACTERS) {
      setRequestError(`Please keep your message under ${MAX_INPUT_CHARACTERS} characters.`);
      return;
    }

    setPlayerIdError("");
    setRequestError("");

    const userMessage: ChatMessage = {
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      role: "user",
      text: trimmed,
    };

    setMessageText("");
    setIsSending(true);
    setSessions((currentSessions) =>
      sortSessionsByRecency(
        currentSessions.map((session) => {
          if (session.id !== activeSession.id) {
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
            messages: [...session.messages, userMessage],
          };
        })
      )
    );

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: trimmed,
          campaign_id: activeSession.campaign_id ?? null,
          character_id: null,
          player_id: normalizedPlayerId,
        }),
      });

      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        const userMessage = getUserFacingErrorMessage(
          response.status,
          typeof result?.error === "string" ? result.error : "The hall did not respond."
        );
        setRequestError(userMessage);

        const assistantMessage: ChatMessage = {
          id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
          role: "assistant",
          text: userMessage,
        };

        setSessions((currentSessions) =>
          sortSessionsByRecency(
            currentSessions.map((session) =>
              session.id === activeSession.id
                ? {
                    ...session,
                    last_message: userMessage,
                    updated_at: Date.now(),
                    conversation_loaded: true,
                    messages: [...session.messages, assistantMessage],
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
            session.id === activeSession.id
              ? {
                  ...session,
                  campaign_id: session.campaign_id ?? returnedCampaignId,
                  last_message: hallReply,
                  updated_at: Date.now(),
                  conversation_loaded: true,
                  messages: [...session.messages, assistantMessage],
                }
              : session
          )
        )
      );

    } catch {
      const assistantMessage: ChatMessage = {
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        role: "assistant",
        text: "The hall cannot respond right now. Please try again later.",
      };

      setSessions((currentSessions) =>
        sortSessionsByRecency(
          currentSessions.map((session) =>
            session.id === activeSession.id
              ? {
                  ...session,
                  last_message: assistantMessage.text,
                  updated_at: Date.now(),
                  conversation_loaded: true,
                  messages: [...session.messages, assistantMessage],
                }
              : session
          )
        )
      );
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="h-screen overflow-hidden bg-[#09090c] text-white">
      <div className="flex h-full w-full gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <SessionHistorySidebar
          sessions={sessions}
          activeSessionId={activeSession?.id ?? ""}
          onSelectSession={handleSelectSession}
          onNewSession={handleNewSession}
          isCreating={isCreatingSession || isCreatingTransitionPending}
        />

        <main className="flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-[32px] border border-white/10 bg-slate-950/90 p-6 shadow-2xl shadow-black/20">
          <header className="mb-6 flex items-center justify-between gap-4 rounded-3xl border border-white/10 bg-white/5 p-5">
            <div>
              <p className="text-sm uppercase tracking-[0.28em] text-sky-300/80">Dungeon MUD</p>
              <h1 className="mt-2 text-3xl font-semibold text-white">Chat with the haunted halls</h1>
            </div>
            <div className="flex flex-col gap-2">
              <label htmlFor="player-id" className="text-xs uppercase tracking-[0.24em] text-zinc-400">
                Player ID
              </label>
              <input
                id="player-id"
                value={playerId}
                onChange={(event) => {
                  setPlayerId(event.target.value);
                  if (playerIdError) {
                    setPlayerIdError("");
                  }
                }}
                placeholder="Enter a real player identifier"
                className="rounded-2xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none transition focus:border-sky-500/60"
              />
              {playerIdError ? <p className="text-xs text-rose-400">{playerIdError}</p> : null}
              {requestError ? <p className="text-xs text-amber-300">{requestError}</p> : null}
            </div>
            <div className="rounded-3xl bg-white/5 px-4 py-3 text-sm text-zinc-300">
              {activeSession ? activeSession.messages.length : 0} message{activeSession?.messages.length === 1 ? "" : "s"}
            </div>
          </header>

          <div className="flex h-full min-h-0 flex-col gap-6">
            <div className="flex-1 min-h-0 overflow-hidden rounded-3xl border border-white/10 bg-black/40 p-4">
              {hasMessages ? (
                <ConversationView messages={activeSession?.messages ?? []} />
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
                disabled={
                  isSending ||
                  messageText.trim().length === 0 ||
                  messageText.trim().length > MAX_INPUT_CHARACTERS ||
                  isCreatingSession ||
                  !playerId.trim() ||
                  playerId.trim().toLowerCase() === "anonymous"
                }
              />
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
