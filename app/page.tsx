"use client";

import { useEffect, useMemo, useState } from "react";
import ChatInput from "@/components/ChatInput";
import ConversationView from "@/components/ConversationView";
import SessionHistorySidebar from "@/components/SessionHistorySidebar";
import type { CampaignDetailsResponse, CampaignSummary, ChatMessage, ChatSession } from "@/types/chat";

const MAX_INPUT_CHARACTERS = 2000;

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
    messages: [],
  };
}

export default function Home() {
  const [sessions, setSessions] = useState<ChatSession[]>([
    createSession("New adventure"),
  ]);
  const [activeSessionId, setActiveSessionId] = useState(sessions[0].id);
  const [messageText, setMessageText] = useState("");
  const [playerId, setPlayerId] = useState("player-1");
  const [playerIdError, setPlayerIdError] = useState("");
  const [requestError, setRequestError] = useState("");
  const [isSending, setIsSending] = useState(false);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) ?? sessions[0],
    [sessions, activeSessionId]
  );

  const hasMessages = activeSession.messages.length > 0;

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
          const remoteCampaignIds = new Set(data.map((campaign) => campaign.campaign_id));
          const existingRemoteSessions = currentSessions.filter(
            (session) => session.campaign_id && remoteCampaignIds.has(session.campaign_id)
          );
          const remainingSessions = currentSessions.filter(
            (session) => !session.campaign_id || !remoteCampaignIds.has(session.campaign_id)
          );

          const hydratedCampaignSessions = data.map((campaign) => {
            const existingSession = existingRemoteSessions.find(
              (session) => session.campaign_id === campaign.campaign_id
            );

            return existingSession
              ? {
                  ...existingSession,
                  title: campaign.title || existingSession.title,
                  player_id: existingSession.player_id ?? normalizedPlayerId,
                  last_message: campaign.last_message,
                }
              : createSession(campaign.title, campaign.campaign_id, normalizedPlayerId, campaign.last_message);
          });

          return [...hydratedCampaignSessions, ...remainingSessions];
        });
      } catch {
        // Ignore campaign loading failures and keep the local session flow intact.
      }
    };

    void loadCampaignSummaries();
  }, [playerId]);

  const loadCampaignConversation = async (sessionId: string, campaignId: string, currentPlayerId: string) => {
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
              }
            : session
        )
      );
    } catch {
      // Ignore campaign hydration failures and leave the current session intact.
    }
  };

  const handleNewSession = () => {
    const nextSession = createSession(`Adventure ${sessions.length + 1}`);
    setSessions((current) => [nextSession, ...current]);
    setActiveSessionId(nextSession.id);
    setMessageText("");
  };

  const handleSelectSession = async (id: string) => {
    const selectedSession = sessions.find((session) => session.id === id);
    setActiveSessionId(id);
    setMessageText("");

    if (!selectedSession?.campaign_id) {
      return;
    }

    if (selectedSession.messages.length > 0) {
      return;
    }

    await loadCampaignConversation(id, selectedSession.campaign_id, playerId.trim());
  };

  const handleSendMessage = async () => {
    const trimmed = messageText.trim();
    const normalizedPlayerId = playerId.trim();

    if (!trimmed || isSending) {
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
      currentSessions.map((session) =>
        session.id === activeSession.id
          ? { ...session, messages: [...session.messages, userMessage] }
          : session
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
          currentSessions.map((session) =>
            session.id === activeSession.id
              ? { ...session, messages: [...session.messages, assistantMessage] }
              : session
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
        currentSessions.map((session) =>
          session.id === activeSession.id
            ? {
                ...session,
                campaign_id: session.campaign_id ?? returnedCampaignId,
                messages: [...session.messages, assistantMessage],
              }
            : session
        )
      );

    } catch {
      const assistantMessage: ChatMessage = {
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        role: "assistant",
        text: "The hall cannot respond right now. Please try again later.",
      };

      setSessions((currentSessions) =>
        currentSessions.map((session) =>
          session.id === activeSession.id
            ? { ...session, messages: [...session.messages, assistantMessage] }
            : session
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
          activeSessionId={activeSessionId}
          onSelectSession={handleSelectSession}
          onNewSession={handleNewSession}
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
              {activeSession.messages.length} message{activeSession.messages.length === 1 ? "" : "s"}
            </div>
          </header>

          <div className="flex h-full min-h-0 flex-col gap-6">
            <div className="flex-1 min-h-0 overflow-hidden rounded-3xl border border-white/10 bg-black/40 p-4">
              {hasMessages ? (
                <ConversationView messages={activeSession.messages} />
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
