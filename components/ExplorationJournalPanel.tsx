"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import { ArrowLeft, ChevronDown, LocateFixed, X } from "lucide-react";
import ExplorationMap from "@/components/ExplorationMap";
import type { ExplorationResponse, ExplorationRoomNotes } from "@/types/exploration";

type Loaded<T> = { status: "error"; message: string } | { status: "empty" } | { status: "loaded"; data: T };
// A result is only valid for the exact request that produced it.
type Keyed<T> = { requestKey: string; result: Loaded<T> } | null;

function graphErrorMessage(status: number) {
  return status === 401 ? "Sign in again to view the exploration journal." : "The exploration journal could not be loaded.";
}

function notesErrorMessage(status: number) {
  if (status === 401) {
    return "Sign in again to view this room.";
  }
  return status === 404 ? "No notes are available for this room." : "The room notes could not be loaded.";
}

async function fetchJson<T>(url: string, signal: AbortSignal): Promise<{ ok: true; body: T } | { ok: false; status: number }> {
  const response = await fetch(url, { signal, cache: "no-store" });
  if (!response.ok) {
    return { ok: false, status: response.status };
  }
  return { ok: true, body: (await response.json()) as T };
}

function Section({
  title,
  isOpen,
  onToggle,
  children,
}: {
  title: string;
  isOpen: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  const regionId = useId();
  return (
    <section className="rounded-2xl border border-white/10 bg-white/5">
      <h3>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={isOpen}
          aria-controls={regionId}
          className="flex w-full items-center justify-between gap-2 rounded-2xl px-4 py-3 text-left text-sm font-semibold text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
        >
          <span>{title}</span>
          <ChevronDown
            className={`h-4 w-4 text-zinc-400 transition-transform motion-reduce:transition-none ${isOpen ? "" : "-rotate-90"}`}
            aria-hidden="true"
          />
        </button>
      </h3>
      <div id={regionId} hidden={!isOpen} className="px-4 pb-4">
        {children}
      </div>
    </section>
  );
}

const RETRY_CLASS =
  "inline-flex h-8 items-center justify-center rounded-lg border border-white/15 px-3 text-xs font-semibold text-zinc-200 transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70";

// Mount with `key={campaignId}` so selection and collapse state never leak between campaigns.
export default function ExplorationJournalPanel({
  id,
  campaignId,
  refreshKey,
  closeLabel,
  closeText,
  onClose,
  className,
  autoFocusClose,
}: {
  id?: string;
  campaignId: string;
  // Changes whenever the game state may have changed (e.g. a turn completed) so the journal refetches.
  refreshKey: number;
  closeLabel: string;
  closeText?: string;
  onClose: () => void;
  className?: string;
  autoFocusClose?: boolean;
}) {
  const [mapOpen, setMapOpen] = useState(true);
  const [journalOpen, setJournalOpen] = useState(true);
  // null = follow the current room.
  const [pickedRoomId, setPickedRoomId] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [graphState, setGraphState] = useState<Keyed<ExplorationResponse>>(null);
  const [notesState, setNotesState] = useState<Keyed<ExplorationRoomNotes>>(null);

  const graphKey = `${campaignId}:${refreshKey}:${attempt}`;
  // During a background refresh keep showing the previous graph instead of flashing a spinner.
  // A stale error is dropped so Retry shows the loading state again.
  const graph = graphState && (graphState.result.status !== "error" || graphState.requestKey === graphKey) ? graphState.result : null;

  useEffect(() => {
    const controller = new AbortController();
    const settle = (result: Loaded<ExplorationResponse>) => setGraphState({ requestKey: graphKey, result });
    void (async () => {
      try {
        const res = await fetchJson<Partial<ExplorationResponse>>(
          `/api/campaign/${encodeURIComponent(campaignId)}/exploration`,
          controller.signal
        );
        if (controller.signal.aborted) {
          return;
        }
        if (!res.ok) {
          // The engine answers 404 until the campaign has any state to project.
          settle(res.status === 404 ? { status: "empty" } : { status: "error", message: graphErrorMessage(res.status) });
          return;
        }
        const body = res.body;
        if (
          typeof body?.current_location?.id !== "string" ||
          !Array.isArray(body.nodes) ||
          !Array.isArray(body.edges) ||
          !Array.isArray(body.observations)
        ) {
          settle({ status: "error", message: graphErrorMessage(500) });
          return;
        }
        settle({ status: "loaded", data: body as ExplorationResponse });
      } catch {
        if (!controller.signal.aborted) {
          settle({ status: "error", message: graphErrorMessage(500) });
        }
      }
    })();
    return () => controller.abort();
  }, [campaignId, graphKey]);

  const loadedGraph = graph?.status === "loaded" ? graph.data : null;
  const currentId = loadedGraph?.current_location.id ?? null;
  // A pick that is no longer a visited room falls back to the current room.
  const pickIsVisited = Boolean(
    loadedGraph && pickedRoomId && loadedGraph.nodes.some((node) => node.kind === "room" && node.id === pickedRoomId)
  );
  const selectedId = pickIsVisited ? pickedRoomId : currentId;
  const viewingHistory = Boolean(selectedId && currentId && selectedId !== currentId);

  const notesKey = `${campaignId}:${selectedId}:${refreshKey}:${attempt}`;
  useEffect(() => {
    if (!viewingHistory || !selectedId) {
      return;
    }
    const controller = new AbortController();
    const settle = (result: Loaded<ExplorationRoomNotes>) => setNotesState({ requestKey: notesKey, result });
    void (async () => {
      try {
        const res = await fetchJson<Partial<ExplorationRoomNotes>>(
          `/api/campaign/${encodeURIComponent(campaignId)}/exploration/rooms/${encodeURIComponent(selectedId)}`,
          controller.signal
        );
        if (controller.signal.aborted) {
          return;
        }
        if (!res.ok) {
          settle({ status: "error", message: notesErrorMessage(res.status) });
          return;
        }
        const body = res.body;
        if (typeof body?.room?.name !== "string" || !Array.isArray(body.notes)) {
          settle({ status: "error", message: notesErrorMessage(500) });
          return;
        }
        settle({ status: "loaded", data: body as ExplorationRoomNotes });
      } catch {
        if (!controller.signal.aborted) {
          settle({ status: "error", message: notesErrorMessage(500) });
        }
      }
    })();
    return () => controller.abort();
  }, [campaignId, selectedId, viewingHistory, notesKey]);

  const selectRoom = (roomId: string) => {
    setPickedRoomId(roomId === currentId ? null : roomId);
    setJournalOpen(true);
  };

  const notesResult = notesState?.requestKey === notesKey ? notesState.result : null;
  const selectedNode = loadedGraph?.nodes.find((node) => node.id === selectedId);

  let journalBody: ReactNode;
  if (!loadedGraph || !selectedId) {
    journalBody = <p className="text-sm text-zinc-500">Select a room on the map once you have explored.</p>;
  } else {
    const heading = (name: string) => <p className="break-words text-base font-semibold text-white">{name}</p>;
    let notes: string[] | null = null;
    let status: ReactNode = null;
    let name = selectedNode?.name ?? loadedGraph.current_location.name;
    if (!viewingHistory) {
      notes = loadedGraph.observations;
    } else if (notesResult === null) {
      status = <p className="animate-pulse text-sm text-zinc-400">Loading notes...</p>;
    } else if (notesResult.status === "error") {
      status = (
        <div className="space-y-3 text-sm">
          <p className="text-rose-300">{notesResult.message}</p>
          <button type="button" onClick={() => setAttempt((current) => current + 1)} className={RETRY_CLASS}>
            Retry
          </button>
        </div>
      );
    } else if (notesResult.status === "loaded") {
      notes = notesResult.data.notes;
      name = notesResult.data.room.name;
    }
    journalBody = (
      <div className="space-y-3" aria-live="polite" aria-busy={viewingHistory && notesResult === null}>
        {heading(name)}
        {viewingHistory ? (
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-xs text-zinc-400">Last-known notes from your earlier visit.</p>
            <button
              type="button"
              onClick={() => setPickedRoomId(null)}
              className={`${RETRY_CLASS} gap-1.5`}
            >
              <LocateFixed className="h-3.5 w-3.5" aria-hidden="true" />
              Return to Current Room
            </button>
          </div>
        ) : null}
        {status}
        {notes === null ? null : notes.length === 0 ? (
          <p className="text-sm text-zinc-500">Nothing noteworthy recorded for this room yet.</p>
        ) : (
          <ul className="list-disc space-y-2 pl-5 text-sm leading-6 text-zinc-300 marker:text-zinc-600">
            {notes.map((note, index) => (
              <li key={`${index}:${note}`} className="break-words">
                {note}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <div id={id} className={`flex h-full w-full min-w-0 flex-col overflow-hidden ${className ?? ""}`}>
      <div className="flex h-full w-full flex-col gap-4 overflow-hidden rounded-3xl bg-zinc-950/95 p-4 shadow-xl">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-xl font-medium tracking-tight text-zinc-100">Exploration Journal</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={closeLabel}
            title={closeLabel}
            autoFocus={autoFocusClose}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-zinc-700/70 bg-zinc-900/20 px-2.5 text-xs font-semibold text-zinc-300 transition-[background-color,border-color,color] duration-300 ease-in-out hover:border-zinc-500 hover:bg-zinc-900/60 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
          >
            {closeText ? <ArrowLeft className="h-4 w-4" aria-hidden="true" /> : <X className="h-4 w-4" aria-hidden="true" />}
            {closeText ? <span>{closeText}</span> : null}
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1 custom-scrollbar">
          {graph === null ? (
            <p className="animate-pulse text-sm text-zinc-400" aria-live="polite">Loading exploration journal...</p>
          ) : graph.status === "error" ? (
            <div className="space-y-3 text-sm">
              <p className="text-rose-300">{graph.message}</p>
              <button type="button" onClick={() => setAttempt((current) => current + 1)} className={RETRY_CLASS}>
                Retry
              </button>
            </div>
          ) : graph.status === "empty" ? (
            <p className="text-sm text-zinc-400">Nothing explored yet. Rooms you visit will appear here.</p>
          ) : (
            <>
              <Section title="Exploration Map" isOpen={mapOpen} onToggle={() => setMapOpen((open) => !open)}>
                <ExplorationMap
                  nodes={graph.data.nodes}
                  edges={graph.data.edges}
                  currentRoomId={graph.data.current_location.id}
                  selectedRoomId={selectedId ?? graph.data.current_location.id}
                  onSelectRoom={selectRoom}
                />
              </Section>
              <Section title="Journal Entry" isOpen={journalOpen} onToggle={() => setJournalOpen((open) => !open)}>
                {journalBody}
              </Section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
