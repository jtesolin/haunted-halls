"use client";

import Image from "next/image";
import { PanelLeftClose } from "lucide-react";

type SessionSummary = {
  id: string;
  title: string;
  messages: { id: string; text: string; is_loading?: boolean }[];
  last_message?: string | null;
  is_optimistic?: boolean;
};

export default function CampaignSidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  onDeleteAllSessions,
  isCreating,
  isDeletingAll,
  deletingSessionIds,
  onToggleSidebar,
  isMobileViewport,
  isSidebarVisible,
  id,
  className,
  contentClassName,
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
  onToggleSidebar?: () => void;
  isMobileViewport?: boolean;
  isSidebarVisible?: boolean;
  id?: string;
  className?: string;
  contentClassName?: string;
}) {
  const deletingIds = new Set(deletingSessionIds ?? []);
  const hasDeletableSessions = sessions.some((session) => !session.is_optimistic);

  return (
    <div id={id} className={`flex h-full w-full min-w-0 flex-col overflow-hidden ${className ?? ""}`}>
      <div
        className={`h-full whitespace-nowrap transition-all duration-200 motion-reduce:transition-none ${
          contentClassName ?? ""
        }`}
      >
        <div className="flex h-full w-full flex-col gap-4 overflow-hidden rounded-3xl bg-zinc-950/95 p-4 shadow-xl">
          <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-4">
                <Image
                  src="/haunted-halls-door-icon-transparent-2.png"
                  alt="Haunted Halls"
                  width={48}
                  height={48}
                  className="h-12 w-12 shrink-0 object-contain"
                />
                <h2 className="whitespace-nowrap text-2xl font-semibold tracking-tight text-white">Haunted Halls</h2>
              </div>

              {onToggleSidebar ? (
                <button
                  type="button"
                  onClick={onToggleSidebar}
                  aria-label={isMobileViewport ? "Close sidebar" : "Collapse sidebar"}
                  aria-expanded={isSidebarVisible}
                  aria-controls={id}
                  title={isMobileViewport ? "Close sidebar" : "Collapse sidebar"}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-700/70 bg-zinc-900/20 text-zinc-400 transition-[background-color,border-color,color] duration-300 ease-in-out hover:border-zinc-500 hover:bg-zinc-900/60 hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                >
                  <PanelLeftClose className="h-4 w-4" aria-hidden="true" />
                </button>
              ) : null}
            </div>

            <div className="flex items-center justify-between gap-2">
              <h3 className="text-xl font-medium tracking-tight text-zinc-100">Campaigns</h3>

              <div className="flex items-center gap-2">
                <span
                  className="group relative inline-flex"
                  tabIndex={!hasDeletableSessions || isDeletingAll || isCreating ? 0 : -1}
                  aria-describedby={!isDeletingAll ? "delete-all-campaigns-tooltip" : undefined}
                >
                  <button
                    type="button"
                    aria-label="Delete all campaigns"
                    onClick={onDeleteAllSessions}
                    disabled={!hasDeletableSessions || isDeletingAll || isCreating}
                    className={`inline-flex h-9 items-center justify-center rounded-lg border transition-[background-color,border-color,color] duration-300 ease-in-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/70 disabled:cursor-not-allowed disabled:border-zinc-700 disabled:bg-transparent disabled:text-zinc-600 ${
                      isDeletingAll
                        ? "gap-2 border-rose-500/30 bg-rose-500/10 px-3 text-xs font-semibold text-rose-200"
                        : "w-9 border-zinc-700/70 bg-transparent text-zinc-500 hover:border-rose-500/30 hover:bg-rose-500/10 hover:text-rose-300"
                    }`}
                  >
                    {isDeletingAll ? (
                      <>
                        <span
                          aria-hidden="true"
                          className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-rose-200/70 border-t-transparent"
                        />
                        Deleting...
                      </>
                    ) : (
                      <svg viewBox="0 0 24 24" aria-hidden="true" className="h-[22px] w-[22px] stroke-current" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M4 6h8" />
                        <path d="M4 12h6" />
                        <path d="M4 18h5" />
                        <path d="m14 10 6 6" />
                        <path d="m20 10-6 6" />
                      </svg>
                    )}
                  </button>
                  {!isDeletingAll ? (
                    <span
                      id="delete-all-campaigns-tooltip"
                      role="tooltip"
                      className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 -translate-x-1/2 whitespace-nowrap rounded-md border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-xs font-medium text-zinc-100 opacity-0 shadow-lg transition group-hover:opacity-100 group-focus-within:opacity-100"
                    >
                      Delete all campaigns
                    </span>
                  ) : null}
                </span>
                <span
                  className="group relative inline-flex"
                  tabIndex={isCreating || isDeletingAll ? 0 : -1}
                  aria-describedby={!isCreating ? "create-campaign-tooltip" : undefined}
                >
                  <button
                    type="button"
                    aria-label="Create new campaign"
                    onClick={onNewSession}
                    disabled={isCreating || isDeletingAll}
                    className={`inline-flex h-9 items-center justify-center rounded-lg bg-sky-500 text-sm font-semibold text-white transition-[background-color,border-color,color] duration-300 ease-in-out hover:bg-sky-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 disabled:cursor-not-allowed disabled:bg-slate-600 ${
                      isCreating ? "gap-2 px-3" : "gap-1.5 px-3"
                    }`}
                  >
                    {isCreating ? (
                      <>
                        <span
                          aria-hidden="true"
                          className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/80 border-t-transparent"
                        />
                        Creating...
                      </>
                    ) : (
                      <>
                        <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4 stroke-current" fill="none" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M12 5v14" />
                          <path d="M5 12h14" />
                        </svg>
                      </>
                    )}
                  </button>
                  {!isCreating ? (
                    <span
                      id="create-campaign-tooltip"
                      role="tooltip"
                      className="pointer-events-none absolute right-0 top-full z-20 mt-2 whitespace-nowrap rounded-md border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-xs font-medium text-zinc-100 opacity-0 shadow-lg transition group-hover:opacity-100 group-focus-within:opacity-100"
                    >
                      Create new campaign
                    </span>
                  ) : null}
                </span>
              </div>
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
        </div>
      </div>
    </div>
  );
}
