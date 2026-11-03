"use client";

export type AvatarPhase = "idle" | "listening" | "thinking" | "speaking";

const LABEL: Record<AvatarPhase, string> = {
  idle: "待命",
  listening: "在听",
  thinking: "在想",
  speaking: "在说",
};

type AvatarSize = "hero" | "compact";

const SIZE: Record<
  AvatarSize,
  { wrap: string; img: string; ring: string; label: string }
> = {
  hero: {
    wrap: "h-[min(58vw,20rem)] w-[min(58vw,20rem)] sm:h-80 sm:w-80",
    img: "h-[92%] w-[92%]",
    ring: "ring-8",
    label: "mt-5 text-base tracking-[0.2em]",
  },
  compact: {
    wrap: "h-28 w-28",
    img: "h-24 w-24",
    ring: "ring-4",
    label: "mt-2 text-xs tracking-wide",
  },
};

export function Avatar({
  phase,
  size = "hero",
}: {
  phase: AvatarPhase;
  size?: AvatarSize;
}) {
  const listening = phase === "listening";
  const speaking = phase === "speaking";
  const thinking = phase === "thinking";
  const s = SIZE[size];

  return (
    <div className="flex flex-col items-center">
      <div
        className={`relative flex items-center justify-center overflow-hidden rounded-full border border-slate-700/80 bg-slate-900/80 ${s.wrap} ${
          listening ? `${s.ring} ring-indigo-400/45` : ""
        } ${speaking ? `${s.ring} ring-emerald-300/40` : ""} ${
          thinking ? "ring-2 ring-amber-300/35" : ""
        }`}
      >
        <div
          className={`flex h-full w-full items-center justify-center ${
            phase === "idle" || speaking ? "super-breathe" : ""
          }`}
        >
          <img
            src="/super-ai-avatar.jpg"
            alt=""
            className={`${s.img} rounded-full object-cover object-[center_22%]`}
          />
        </div>
      </div>
      <p className={`${s.label} text-slate-400`}>{LABEL[phase]}</p>
    </div>
  );
}
