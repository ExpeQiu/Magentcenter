import type { TaskInfo } from "@/lib/types";

const STYLES: Record<string, string> = {
  queued: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  running: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  completed: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  failed: "bg-red-500/15 text-red-300 ring-red-500/30",
  cancelled: "bg-slate-500/15 text-slate-300 ring-slate-500/30",
  timeout: "bg-orange-500/15 text-orange-300 ring-orange-500/30",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STYLES[status] || "bg-slate-700 text-slate-300"}`}
    >
      {status}
    </span>
  );
}

export function formatTime(iso: string) {
  return new Date(iso).toLocaleString("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function truncate(s: string, n = 80) {
  return s.length > n ? s.slice(0, n) + "…" : s;
}
