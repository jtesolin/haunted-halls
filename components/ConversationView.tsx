"use client";

import { useEffect, useRef } from "react";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  is_loading?: boolean;
};

export default function ConversationView({ messages }: { messages: ChatMessage[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) {
      return;
    }

    element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
  }, [messages.length]);

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
            <p className="whitespace-pre-wrap break-words">{message.text}</p>
            {message.is_loading ? (
              <p className="mt-2 animate-pulse text-xs uppercase tracking-[0.14em] text-zinc-400">Loading opening...</p>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
