"use client";

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
      <div className="flex gap-3">
        <input
          id="mud-input"
          type="text"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="Type a command or message..."
          className="w-full rounded-2xl border border-white/10 bg-zinc-900 px-4 py-3 text-sm text-white outline-none transition focus:border-sky-500/70 focus:ring-1 focus:ring-sky-500/40"
        />
        <button
          type="submit"
          disabled={disabled}
          className="inline-flex h-12 items-center justify-center rounded-2xl bg-sky-500 px-5 text-sm font-semibold text-white transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:bg-slate-600"
        >
          Send
        </button>
      </div>
    </form>
  );
}
