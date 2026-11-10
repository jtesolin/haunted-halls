"use client";

import Image from "next/image";
import { useEffect, useRef } from "react";
import { BookOpen, Menu, User } from "lucide-react";

export type NavPanel = "campaigns" | "character";

const RAIL_BUTTON_CLASS =
  "inline-flex h-9 w-9 items-center justify-center rounded-lg border transition-[background-color,border-color,color] duration-300 ease-in-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 disabled:cursor-not-allowed disabled:opacity-40";
const RAIL_IDLE_CLASS =
  "border-zinc-700/70 bg-zinc-900/20 text-zinc-400 hover:border-zinc-500 hover:bg-zinc-900/60 hover:text-zinc-200";
const RAIL_SELECTED_CLASS = "border-sky-500/60 bg-sky-500/15 text-sky-200";

export const CHARACTER_UNAVAILABLE_HINT = "Character Sheet is available once the campaign has a character";

export default function CampaignToolbar({
  isMobileViewport,
  desktopPanel,
  mobileView,
  isCharacterAvailable,
  onToggleDesktopPanel,
  onOpenMobileMenu,
  onSelectMobilePanel,
  onCloseMobile,
  onNewSession,
  isNewSessionDisabled,
}: {
  isMobileViewport: boolean;
  desktopPanel: NavPanel | null;
  mobileView: "menu" | NavPanel | null;
  isCharacterAvailable: boolean;
  onToggleDesktopPanel: (panel: NavPanel) => void;
  onOpenMobileMenu: () => void;
  onSelectMobilePanel: (panel: NavPanel) => void;
  onCloseMobile: () => void;
  onNewSession: () => void;
  isNewSessionDisabled?: boolean;
}) {
  const hamburgerRef = useRef<HTMLButtonElement | null>(null);
  const previousMobileViewRef = useRef(mobileView);

  // Return focus to the hamburger whenever a mobile menu/panel closes back to the conversation.
  useEffect(() => {
    if (previousMobileViewRef.current !== null && mobileView === null && isMobileViewport) {
      hamburgerRef.current?.focus();
    }
    previousMobileViewRef.current = mobileView;
  }, [mobileView, isMobileViewport]);

  const characterEnabled = isCharacterAvailable || desktopPanel === "character";

  return (
    <>
      {isMobileViewport ? (
        <>
          <div className="absolute left-3 top-2 z-40 md:hidden">
            <button
              ref={hamburgerRef}
              type="button"
              onClick={onOpenMobileMenu}
              aria-label="Open navigation menu"
              aria-haspopup="dialog"
              aria-expanded={mobileView === "menu"}
              aria-controls="mobile-nav-menu"
              title="Open navigation menu"
              className={`${RAIL_BUTTON_CLASS} ${RAIL_IDLE_CLASS}`}
            >
              <Menu className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>

          {mobileView === "menu" ? (
            <>
              <button
                type="button"
                tabIndex={-1}
                aria-label="Close navigation menu"
                onClick={onCloseMobile}
                className="absolute inset-0 z-40 bg-black/45"
              />
              <div
                id="mobile-nav-menu"
                role="dialog"
                aria-label="Navigation menu"
                className="absolute left-3 top-12 z-50 flex w-56 flex-col gap-1 rounded-2xl border border-white/10 bg-zinc-950 p-2 shadow-xl"
              >
                <button
                  type="button"
                  autoFocus
                  onClick={() => onSelectMobilePanel("campaigns")}
                  className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium text-zinc-100 transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                >
                  <BookOpen className="h-4 w-4" aria-hidden="true" />
                  Campaigns
                </button>
                <button
                  type="button"
                  disabled={!isCharacterAvailable}
                  title={isCharacterAvailable ? undefined : CHARACTER_UNAVAILABLE_HINT}
                  onClick={() => onSelectMobilePanel("character")}
                  className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium text-zinc-100 transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 disabled:cursor-not-allowed disabled:text-zinc-600 disabled:hover:bg-transparent"
                >
                  <User className="h-4 w-4" aria-hidden="true" />
                  Character Sheet
                </button>
                <button
                  type="button"
                  onClick={onCloseMobile}
                  className="rounded-xl px-3 py-2.5 text-left text-sm text-zinc-400 transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                >
                  Back to Conversation
                </button>
              </div>
            </>
          ) : null}
        </>
      ) : null}

      {!isMobileViewport ? (
        <aside
          aria-label="Primary navigation"
          className="relative z-20 hidden h-full min-h-0 md:flex md:flex-col md:items-center md:justify-start md:gap-4 md:py-3"
        >
          <Image
            src="/haunted-halls-door-icon-transparent-2.png"
            alt="Haunted Halls"
            width={48}
            height={48}
            className="h-12 w-12 shrink-0 object-contain"
            priority
          />

          <nav aria-label="Panels" className="flex flex-col items-center gap-1.5">
            <button
              type="button"
              onClick={() => onToggleDesktopPanel("campaigns")}
              aria-label="Campaigns"
              aria-expanded={desktopPanel === "campaigns"}
              aria-controls="campaign-sidebar"
              title="Campaigns"
              className={`${RAIL_BUTTON_CLASS} ${desktopPanel === "campaigns" ? RAIL_SELECTED_CLASS : RAIL_IDLE_CLASS}`}
            >
              <BookOpen className="h-4 w-4" aria-hidden="true" />
            </button>

            <button
              type="button"
              onClick={() => onToggleDesktopPanel("character")}
              disabled={!characterEnabled}
              aria-label="Character Sheet"
              aria-expanded={desktopPanel === "character"}
              aria-controls="character-sheet-panel"
              title={characterEnabled ? "Character Sheet" : CHARACTER_UNAVAILABLE_HINT}
              className={`${RAIL_BUTTON_CLASS} ${desktopPanel === "character" ? RAIL_SELECTED_CLASS : RAIL_IDLE_CLASS}`}
            >
              <User className="h-4 w-4" aria-hidden="true" />
            </button>

            {desktopPanel !== "campaigns" ? (
              <button
                type="button"
                onClick={onNewSession}
                aria-label="Create new campaign"
                title="Create new campaign"
                disabled={isNewSessionDisabled}
                className="mt-2 inline-flex h-9 w-9 items-center justify-center rounded-lg bg-sky-500 text-white transition-[background-color,border-color,color] duration-300 ease-in-out hover:bg-sky-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 disabled:cursor-not-allowed disabled:bg-slate-600"
              >
                <svg
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                  className="h-4 w-4 stroke-current"
                  fill="none"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M12 5v14" />
                  <path d="M5 12h14" />
                </svg>
              </button>
            ) : null}
          </nav>
        </aside>
      ) : null}
    </>
  );
}
