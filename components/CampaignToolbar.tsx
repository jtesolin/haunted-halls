"use client";

import Image from "next/image";
import { PanelLeftOpen } from "lucide-react";

export default function CampaignToolbar({
  isCollapsed,
  isMobileViewport,
  isSidebarVisible,
  onToggleSidebar,
  onExpandSidebar,
  onNewSession,
  isNewSessionDisabled,
}: {
  isCollapsed: boolean;
  isMobileViewport: boolean;
  isSidebarVisible: boolean;
  onToggleSidebar: () => void;
  onExpandSidebar: () => void;
  onNewSession: () => void;
  isNewSessionDisabled?: boolean;
}) {
  return (
    <>
      {isMobileViewport && !isSidebarVisible ? (
        <div className="absolute left-3 top-2 z-40 md:hidden">
          <button
            type="button"
            onClick={onToggleSidebar}
            aria-label="Open sidebar"
            aria-expanded={false}
            aria-controls="campaign-sidebar"
            title="Open sidebar"
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-700/70 bg-zinc-900/20 text-zinc-400 transition-[background-color,border-color,color] duration-300 ease-in-out hover:border-zinc-500 hover:bg-zinc-900/60 hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
          >
            <PanelLeftOpen className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      ) : null}

      {isCollapsed ? (
        <aside className="relative z-20 hidden h-full min-h-0 md:flex md:flex-col md:items-center md:justify-start md:gap-4 md:py-3">
          <Image
            src="/haunted-halls-door-icon-transparent-2.png"
            alt="Haunted Halls"
            width={48}
            height={48}
            className="h-12 w-12 shrink-0 object-contain"
            priority
          />

          <div className="flex flex-col items-center gap-1.5">
            <button
              type="button"
              onClick={onExpandSidebar}
              aria-label="Expand sidebar"
              aria-expanded={false}
              aria-controls="campaign-sidebar"
              title="Expand sidebar"
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-700/70 bg-zinc-900/20 text-zinc-400 transition-[background-color,border-color,color] duration-300 ease-in-out hover:border-zinc-500 hover:bg-zinc-900/60 hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
            >
              <PanelLeftOpen className="h-4 w-4" aria-hidden="true" />
            </button>

            <button
              type="button"
              onClick={onNewSession}
              aria-label="Create new campaign"
              title="Create new campaign"
              disabled={isNewSessionDisabled}
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-sky-500 text-white transition-[background-color,border-color,color] duration-300 ease-in-out hover:bg-sky-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 disabled:cursor-not-allowed disabled:bg-slate-600"
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
          </div>
        </aside>
      ) : null}
    </>
  );
}