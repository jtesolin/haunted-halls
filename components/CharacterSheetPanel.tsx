"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import { ArrowLeft, ChevronDown, Package, Sparkles, User, X } from "lucide-react";
import type { CharacterDetailResponse } from "@/types/chat";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; character: CharacterDetailResponse };

function errorMessageForStatus(status: number) {
  if (status === 401) {
    return "Sign in again to view this character.";
  }
  if (status === 404) {
    return "This character could not be found.";
  }
  return "The character sheet could not be loaded.";
}

function Section({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(true);
  const regionId = useId();

  return (
    <section className="rounded-2xl border border-white/10 bg-white/5">
      <h4>
        <button
          type="button"
          onClick={() => setIsOpen((current) => !current)}
          aria-expanded={isOpen}
          aria-controls={regionId}
          className="flex w-full items-center justify-between gap-2 rounded-2xl px-4 py-3 text-left text-sm font-semibold text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
        >
          <span>
            {title} <span className="font-normal text-zinc-500">({count})</span>
          </span>
          <ChevronDown
            className={`h-4 w-4 text-zinc-400 transition-transform motion-reduce:transition-none ${
              isOpen ? "" : "-rotate-90"
            }`}
            aria-hidden="true"
          />
        </button>
      </h4>
      <div id={regionId} hidden={!isOpen} className="px-4 pb-4">
        {children}
      </div>
    </section>
  );
}

export default function CharacterSheetPanel({
  id,
  characterId,
  closeLabel,
  closeText,
  onClose,
  className,
  autoFocusClose,
}: {
  id?: string;
  characterId: string | null | undefined;
  closeLabel: string;
  closeText?: string;
  onClose: () => void;
  className?: string;
  autoFocusClose?: boolean;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  // The panel is mounted only while open, so every open (and every retry or
  // character change) fetches fresh details from the engine via the BFF route.
  useEffect(() => {
    if (!characterId) {
      return;
    }

    const controller = new AbortController();
    queueMicrotask(() => {
      if (!controller.signal.aborted) {
        setState({ status: "loading" });
      }
    });

    void (async () => {
      try {
        const response = await fetch(`/api/character/${encodeURIComponent(characterId)}`, {
          signal: controller.signal,
          cache: "no-store",
        });
        if (controller.signal.aborted) {
          return;
        }
        if (!response.ok) {
          setState({ status: "error", message: errorMessageForStatus(response.status) });
          return;
        }
        const data = (await response.json()) as Partial<CharacterDetailResponse>;
        if (controller.signal.aborted) {
          return;
        }
        if (typeof data?.name !== "string") {
          setState({ status: "error", message: errorMessageForStatus(500) });
          return;
        }
        setState({
          status: "loaded",
          character: {
            character_id: data.character_id ?? characterId,
            name: data.name,
            inventory: Array.isArray(data.inventory) ? data.inventory : [],
            abilities: Array.isArray(data.abilities) ? data.abilities : [],
          },
        });
      } catch {
        if (!controller.signal.aborted) {
          setState({ status: "error", message: errorMessageForStatus(500) });
        }
      }
    })();

    return () => controller.abort();
  }, [characterId, attempt]);

  return (
    <div id={id} className={`flex h-full w-full min-w-0 flex-col overflow-hidden ${className ?? ""}`}>
      <div className="flex h-full w-full flex-col gap-4 overflow-hidden rounded-3xl bg-zinc-950/95 p-4 shadow-xl">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-xl font-medium tracking-tight text-zinc-100">Character Sheet</h2>
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

        <div className="min-h-0 flex-1 overflow-y-auto pr-1 custom-scrollbar" aria-live="polite" aria-busy={Boolean(characterId) && state.status === "loading"}>
          {!characterId ? (
            <p className="text-sm text-zinc-400">
              No character is available for this campaign yet. Send a command to begin your adventure.
            </p>
          ) : state.status === "loading" ? (
            <p className="animate-pulse text-sm text-zinc-400">Loading character...</p>
          ) : state.status === "error" ? (
            <div className="space-y-3 text-sm">
              <p className="text-rose-300">{state.message}</p>
              <button
                type="button"
                onClick={() => setAttempt((current) => current + 1)}
                className="inline-flex h-8 items-center justify-center rounded-lg border border-white/15 px-3 text-xs font-semibold text-zinc-200 transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
              >
                Retry
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <div
                  className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full border border-white/15 bg-zinc-800 text-zinc-400"
                  aria-hidden="true"
                >
                  <User className="h-7 w-7" />
                </div>
                <p className="min-w-0 break-words text-lg font-semibold text-white">{state.character.name}</p>
              </div>

              <Section title="Abilities" count={state.character.abilities.length}>
                {state.character.abilities.length === 0 ? (
                  <p className="text-sm text-zinc-500">No abilities yet.</p>
                ) : (
                  <ul className="space-y-3">
                    {state.character.abilities.map((ability) => (
                      <li key={ability.ability_id} className="flex gap-3">
                        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-sky-300" aria-hidden="true" />
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-zinc-100">{ability.display_name}</p>
                          <p className="text-xs leading-5 text-zinc-400">{ability.description}</p>
                          {!ability.available ? (
                            <p className="text-xs leading-5 text-amber-300">
                              Unavailable{ability.availability_reason ? `: ${ability.availability_reason}` : ""}
                            </p>
                          ) : null}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>

              <Section title="Inventory" count={state.character.inventory.length}>
                {state.character.inventory.length === 0 ? (
                  <p className="text-sm text-zinc-500">Your inventory is empty.</p>
                ) : (
                  <ul className="space-y-3">
                    {state.character.inventory.map((item) => (
                      <li key={item.id} className="flex gap-3">
                        <Package className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" aria-hidden="true" />
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-zinc-100">
                            {item.name}
                            {item.quantity > 1 ? (
                              <span className="ml-1.5 font-normal text-zinc-500">×{item.quantity}</span>
                            ) : null}
                          </p>
                          <p className="text-xs leading-5 text-zinc-400">{item.description}</p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
