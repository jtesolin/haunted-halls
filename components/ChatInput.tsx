"use client";

import { useEffect, useRef, useState } from "react";

export default function ChatInput({
  value,
  onChange,
  onSend,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  disabled?: boolean;
}) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [isOverflowing, setIsOverflowing] = useState(false);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }

    textarea.style.height = "auto";
    const targetHeight = Math.min(textarea.scrollHeight, window.innerHeight * 0.25);
    textarea.style.height = `${targetHeight}px`;
    setIsOverflowing(textarea.scrollHeight > targetHeight);
  }, [value]);

  return (
    <form
      className="rounded-3xl border border-white/10 bg-zinc-950/90 p-4 shadow-inner"
      onSubmit={(event) => {
        event.preventDefault();
        onSend();
      }}
    >
      <label htmlFor="mud-input" className="sr-only">
        Enter your command
      </label>
      <div className="flex flex-col gap-3 sm:flex-row">
        <textarea
          id="mud-input"
          ref={textareaRef}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              if (event.shiftKey) {
                return;
              }
              event.preventDefault();
              onSend();
            }
          }}
          placeholder="Type a command or message..."
          rows={1}
          className={`min-h-[3rem] w-full resize-none rounded-2xl border border-white/10 bg-zinc-900 px-4 py-3 text-sm leading-6 text-white outline-none transition focus:border-sky-500/70 focus:ring-1 focus:ring-sky-500/40 max-h-[25vh] ${
            isOverflowing
              ? "overflow-y-auto custom-scrollbar"
              : "overflow-y-hidden"
          }`}
        />
        <button
          type="submit"
          disabled={disabled}
          className="inline-flex h-12 shrink-0 items-center justify-center rounded-2xl bg-sky-500 px-5 text-sm font-semibold text-white transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:bg-slate-600"
        >
          Send
        </button>
      </div>
    </form>
  );
}
