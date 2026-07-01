"use client";

type SessionSummary = {
  id: string;
  title: string;
  messages: { id: string; text: string; is_loading?: boolean }[];
  last_message?: string | null;
  is_optimistic?: boolean;
};

export default function SessionHistorySidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  isCreating,
}: {
  sessions: SessionSummary[];
  activeSessionId: string;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  isCreating?: boolean;
}) {
  return (
    <aside className="flex h-full w-full max-w-[320px] flex-col gap-4 overflow-hidden rounded-3xl border border-white/10 bg-zinc-950/95 p-4 shadow-xl">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-zinc-400">Sessions</p>
          <h2 className="mt-2 text-xl font-semibold text-white">Session history</h2>
        </div>
        <button
          type="button"
          onClick={onNewSession}
          disabled={isCreating}
          className="rounded-full bg-sky-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:bg-slate-600"
        >
          {isCreating ? "Creating..." : "New"}
        </button>
      </div>

      <div className="flex-1 overflow-hidden">
        <div className="space-y-3 h-full overflow-y-auto pr-1 custom-scrollbar">
          {sessions.map((session) => {
            const latestMessage = session.messages[session.messages.length - 1];
            const previewText = session.last_message ?? latestMessage?.text ?? null;
            const isLoading = Boolean(session.is_optimistic || latestMessage?.is_loading);

            return (
              <button
              key={session.id}
              type="button"
              onClick={() => onSelectSession(session.id)}
              disabled={session.is_optimistic}
              className={`w-full rounded-3xl px-4 py-4 text-left transition ${
                session.id === activeSessionId
                  ? "bg-slate-800 text-white ring-1 ring-sky-500/30"
                  : "bg-white/5 text-zinc-300 hover:bg-white/10"
              } ${session.is_optimistic ? "cursor-wait opacity-90" : ""}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="block text-sm font-semibold text-left">{session.title}</span>
                {isLoading ? (
                  <span className="animate-pulse text-[10px] uppercase tracking-[0.16em] text-zinc-400">Loading</span>
                ) : null}
              </div>
              <p className="mt-2 line-clamp-2 text-xs leading-5 text-zinc-500">
                {previewText
                  ? previewText.length > 90
                    ? `${previewText.slice(0, 87)}...`
                    : previewText
                  : "No messages yet"}
              </p>
            </button>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
