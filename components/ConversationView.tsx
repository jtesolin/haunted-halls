"use client";

import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/types/chat";

export default function ConversationView({
  messages,
  onRetry,
  retryDisabled = false,
}: {
  messages: ChatMessage[];
  onRetry?: (messageId: string) => void;
  retryDisabled?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const latestMessage = messages[messages.length - 1];

  useEffect(() => {
    const element = containerRef.current;
    if (!element) {
      return;
    }

    element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
  }, [latestMessage?.id, latestMessage?.text, messages.length]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto pr-2 custom-scrollbar" ref={containerRef}>
      <div className="flex flex-col gap-4 py-4">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`max-w-[80%] rounded-3xl px-4 py-3 text-sm leading-6 ${
              message.role === "user"
                ? "self-end bg-sky-500 text-white"
                : "self-start bg-white/5 text-zinc-200"
            }`}
          >
            {!message.is_loading ? <p className="whitespace-pre-wrap break-words">{message.text}</p> : null}
            {message.is_loading ? (
              <p className="mt-2 animate-pulse text-xs uppercase tracking-[0.14em] text-zinc-400">
                {message.loading_text ?? "Loading..."}
              </p>
            ) : null}
            {message.failure ? (
              <div className="mt-2 border-t border-white/20 pt-2 text-xs leading-5 text-sky-100">
                {message.failure.title ? <p className="font-semibold">{message.failure.title}</p> : null}
                <p>{message.failure.message}</p>
                {message.failure.retryable && onRetry ? (
                  <button
                    type="button"
                    disabled={retryDisabled}
                    onClick={() => onRetry(message.id)}
                    className="mt-1 font-semibold underline decoration-sky-200/70 underline-offset-2 transition hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
                    aria-label={`Retry sending: ${message.text}`}
                  >
                    Retry
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
