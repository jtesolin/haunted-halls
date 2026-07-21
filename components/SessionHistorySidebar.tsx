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
  onDeleteSession,
  onDeleteAllSessions,
  isCreating,
  isDeletingAll,
  deletingSessionIds,
}: {
  sessions: SessionSummary[];
  activeSessionId: string;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession: (id: string) => void;
  onDeleteAllSessions: () => void;
  isCreating?: boolean;
  isDeletingAll?: boolean;
  deletingSessionIds?: string[];
}) {
  const deletingIds = new Set(deletingSessionIds ?? []);
  const hasDeletableSessions = sessions.some((session) => !session.is_optimistic);

  return (
    <aside className="flex h-full w-full max-w-[320px] flex-col gap-4 overflow-hidden rounded-3xl border border-white/10 bg-zinc-950/95 p-4 shadow-xl">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-zinc-400">Sessions</p>
          <h2 className="mt-2 text-xl font-semibold text-white">Session history</h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onDeleteAllSessions}
            disabled={!hasDeletableSessions || isDeletingAll || isCreating}
            className="inline-flex h-9 items-center gap-1.5 rounded-full border border-rose-500/40 px-3 text-xs font-semibold uppercase tracking-[0.12em] text-rose-200 transition hover:border-rose-400 hover:text-rose-100 disabled:cursor-not-allowed disabled:border-zinc-700 disabled:text-zinc-500"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" className="h-3.5 w-3.5 fill-current">
              <path d="M9 3h6l1 2h5v2H3V5h5l1-2Zm-3 6h12l-1 11a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L6 9Zm3 2v8h2v-8H9Zm4 0v8h2v-8h-2Z" />
            </svg>
            {isDeletingAll ? "Deleting..." : "Delete all"}
          </button>
          <button
            type="button"
            onClick={onNewSession}
            disabled={isCreating || isDeletingAll}
            className="rounded-full bg-sky-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:bg-slate-600"
          >
            {isCreating ? "Creating..." : "New"}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-hidden">
        <div className="space-y-3 h-full overflow-y-auto pr-1 custom-scrollbar">
          {sessions.map((session) => {
            const latestMessage = session.messages[session.messages.length - 1];
            const previewText = session.last_message ?? latestMessage?.text ?? null;
            const isLoading = Boolean(session.is_optimistic || latestMessage?.is_loading);
            const isDeleting = deletingIds.has(session.id);

            return (
              <div key={session.id} className="group relative">
                <button
                  type="button"
                  onClick={() => onSelectSession(session.id)}
                  disabled={session.is_optimistic || isDeleting || isDeletingAll}
                  className={`w-full rounded-3xl px-4 py-4 pr-12 text-left transition ${
                    session.id === activeSessionId
                      ? "bg-slate-800 text-white ring-1 ring-sky-500/30"
                      : "bg-white/5 text-zinc-300 hover:bg-white/10"
                  } ${session.is_optimistic || isDeleting ? "cursor-wait opacity-90" : ""}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="block text-left text-sm font-semibold">{session.title}</span>
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

                <button
                  type="button"
                  aria-label={`Delete session ${session.title}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onDeleteSession(session.id);
                  }}
                  disabled={session.is_optimistic || isDeleting || isDeletingAll}
                  className="absolute right-3 top-3 inline-flex h-8 w-8 items-center justify-center rounded-full border border-transparent bg-transparent text-zinc-500 opacity-0 transition hover:border-rose-400/50 hover:bg-rose-500/10 hover:text-rose-300 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/60 disabled:cursor-not-allowed disabled:opacity-30 group-hover:opacity-100 group-focus-within:opacity-100"
                >
                  {isDeleting ? (
                    <span className="text-[10px] font-semibold uppercase tracking-[0.16em]">...</span>
                  ) : (
                    <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4 fill-current">
                      <path d="M9 3h6l1 2h5v2H3V5h5l1-2Zm-3 6h12l-1 11a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L6 9Zm3 2v8h2v-8H9Zm4 0v8h2v-8h-2Z" />
                    </svg>
                  )}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
