"use client";

import { useEffect, useRef, useState } from "react";

export default function ChatInput({
  value,
  onChange,
  onSend,
  inputDisabled,
  sendDisabled,
  disabledPlaceholder,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  inputDisabled?: boolean;
  sendDisabled?: boolean;
  disabledPlaceholder?: string;
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

  const focusTextarea = () => {
    queueMicrotask(() => {
      textareaRef.current?.focus();
    });
  };

  return (
    <form
      className="rounded-2xl border border-white/10 bg-zinc-950/90 p-2 shadow-inner md:rounded-3xl md:p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (sendDisabled) {
          return;
        }

        onSend();
        focusTextarea();
      }}
    >
      <label htmlFor="mud-input" className="sr-only">
        Enter your command
      </label>
      <div className="flex flex-col gap-2 sm:flex-row md:gap-3">
        <textarea
          id="mud-input"
          ref={textareaRef}
          value={value}
          disabled={inputDisabled}
          aria-disabled={inputDisabled}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== "Enter" || event.shiftKey) {
              return;
            }

            event.preventDefault();
            if (sendDisabled) {
              return;
            }

            onSend();
            focusTextarea();
          }}
          placeholder={inputDisabled ? (disabledPlaceholder ?? "Command input unavailable") : "Type a command or message..."}
          rows={1}
          className={`min-h-[3rem] w-full resize-none rounded-2xl border border-white/10 bg-zinc-900 px-4 py-3 text-sm leading-6 text-white outline-none transition focus:border-sky-500/70 focus:ring-1 focus:ring-sky-500/40 disabled:cursor-not-allowed disabled:opacity-60 max-h-[25vh] ${
            isOverflowing
              ? "overflow-y-auto custom-scrollbar"
              : "overflow-y-hidden"
          }`}
        />
        <button
          type="submit"
          disabled={sendDisabled}
          className="inline-flex h-12 shrink-0 items-center justify-center rounded-2xl bg-sky-500 px-5 text-sm font-semibold text-white transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:bg-slate-600"
        >
          Send
        </button>
      </div>
    </form>
  );
}
