"use client";

type SessionSummary = {
  id: string;
  title: string;
  messages: { id: string }[];
};

export default function SessionHistorySidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
}: {
  sessions: SessionSummary[];
  activeSessionId: string;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
}) {
  return (
    <aside className="flex w-full max-w-[320px] flex-col gap-4 rounded-3xl border border-white/10 bg-zinc-950/95 p-4 shadow-xl">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-zinc-400">Sessions</p>
          <h2 className="mt-2 text-xl font-semibold text-white">Session history</h2>
        </div>
        <button
          type="button"
          onClick={onNewSession}
          className="rounded-full bg-sky-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-400"
        >
          New
        </button>
      </div>

      <div className="space-y-3 overflow-y-auto pr-1">
        {sessions.map((session) => (
          <button
            key={session.id}
            type="button"
            onClick={() => onSelectSession(session.id)}
            className={`w-full rounded-3xl px-4 py-4 text-left transition ${
              session.id === activeSessionId
                ? "bg-slate-800 text-white ring-1 ring-sky-500/30"
                : "bg-white/5 text-zinc-300 hover:bg-white/10"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="block text-sm font-semibold text-left">{session.title}</span>
              <span className="rounded-full bg-white/5 px-2 py-1 text-[11px] text-zinc-400">
                {session.messages.length}
              </span>
            </div>
            <p className="mt-2 text-xs leading-5 text-zinc-500">
              {session.messages.length > 0 ? `${session.messages.length} message${session.messages.length === 1 ? "" : "s"}` : "No messages yet"}
            </p>
          </button>
        ))}
      </div>
    </aside>
  );
}
