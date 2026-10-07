"use client";

export type AvatarPhase = "idle" | "listening" | "thinking" | "speaking";

const LABEL: Record<AvatarPhase, string> = {
  idle: "待命",
  listening: "在听",
  thinking: "在想",
  speaking: "在说",
};

export function Avatar({ phase }: { phase: AvatarPhase }) {
  const listening = phase === "listening";
  const speaking = phase === "speaking";
  const thinking = phase === "thinking";

  return (
    <div className="flex flex-col items-center">
      <div
        className={`relative flex h-72 w-72 items-center justify-center rounded-full border border-slate-800 bg-slate-900/80 ${
          listening ? "ring-4 ring-indigo-400/40" : ""
        } ${thinking ? "ring-2 ring-amber-300/30" : ""}`}
      >
        <div className={phase === "idle" || speaking ? "super-breathe" : ""}>
          <svg viewBox="0 0 200 220" className="h-64 w-64" aria-hidden>
            <ellipse cx="100" cy="168" rx="46" ry="28" fill="#1e293b" />
            <path d="M62 150c8 36 68 36 76 0v-8H62z" fill="#312e81" />
            <circle cx="100" cy="92" r="52" fill="#f1d7c5" />
            <path d="M52 88c6-46 90-46 96 4-18-18-78-22-96-4z" fill="#1e1b4b" />
            <circle cx="82" cy="96" r="4.5" fill="#0f172a" />
            <circle cx="118" cy="96" r="4.5" fill="#0f172a" />
            <path
              d="M86 118c8 8 20 8 28 0"
              fill="none"
              stroke="#9a3412"
              strokeWidth="3"
              strokeLinecap="round"
            />
            <ellipse
              cx="100"
              cy="128"
              rx="10"
              ry="7"
              fill="#7f1d1d"
              className={speaking ? "super-talk" : ""}
              opacity={speaking ? 1 : 0.35}
            />
          </svg>
        </div>
      </div>
      <p className="mt-4 text-sm tracking-wide text-slate-400">{LABEL[phase]}</p>
    </div>
  );
}
