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
        className={`relative flex h-72 w-72 items-center justify-center overflow-hidden rounded-full border border-slate-800 bg-slate-900/80 ${
          listening ? "ring-4 ring-indigo-400/40" : ""
        } ${speaking ? "ring-4 ring-emerald-300/40" : ""} ${
          thinking ? "ring-2 ring-amber-300/30" : ""
        }`}
      >
        <div className={phase === "idle" || speaking ? "super-breathe" : ""}>
          <img
            src="/super-ai-avatar.jpg"
            alt=""
            className="h-64 w-64 rounded-full object-cover object-[center_22%]"
          />
        </div>
      </div>
      <p className="mt-4 text-sm tracking-wide text-slate-400">{LABEL[phase]}</p>
    </div>
  );
}
