"use client";

import { useMemo, useState } from "react";
import ChatInput from "@/components/ChatInput";
import ConversationView from "@/components/ConversationView";
import SessionHistorySidebar from "@/components/SessionHistorySidebar";
import type { ChatMessage, ChatSession } from "@/types/chat";

function createSession(title: string): ChatSession {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    title,
    messages: [],
  };
}

export default function Home() {
  const [sessions, setSessions] = useState<ChatSession[]>([
    createSession("New adventure"),
  ]);
  const [activeSessionId, setActiveSessionId] = useState(sessions[0].id);
  const [messageText, setMessageText] = useState("");
  const [isSending, setIsSending] = useState(false);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) ?? sessions[0],
    [sessions, activeSessionId]
  );

  const hasMessages = activeSession.messages.length > 0;

  const handleNewSession = () => {
    const nextSession = createSession(`Adventure ${sessions.length + 1}`);
    setSessions((current) => [nextSession, ...current]);
    setActiveSessionId(nextSession.id);
    setMessageText("");
  };

  const handleSelectSession = (id: string) => {
    setActiveSessionId(id);
    setMessageText("");
  };

  const handleSendMessage = async () => {
    const trimmed = messageText.trim();
    if (!trimmed || isSending) {
      return;
    }

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
        body: JSON.stringify({ message: trimmed }),
      });

      const result = await response.json();
      const hallReply = typeof result?.reply === "string" ? result.reply : "The hall did not respond.";

      const assistantMessage: ChatMessage = {
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        role: "assistant",
        text: hallReply,
      };

      setSessions((currentSessions) =>
        currentSessions.map((session) =>
          session.id === activeSession.id
            ? { ...session, messages: [...session.messages, assistantMessage] }
            : session
        )
      );
    } catch (error) {
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
                disabled={isSending || messageText.trim().length === 0}
              />
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
