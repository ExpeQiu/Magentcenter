"use client";

import { useMemo } from "react";
import Link from "next/link";
import type { TaskInfo } from "@/lib/types";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import { StatusBadge, truncate } from "@/components/ui/status-badge";

function parseDate(s: string): Date | null {
  if (!s) return null;
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

function dayKey(d: Date) {
  return d.toISOString().slice(0, 10);
}

function addDays(d: Date, n: number) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}

export function TaskGanttView({ tasks }: { tasks: TaskInfo[] }) {
  const wp = useWorkspacePaths();

  const { days, bars, rangeStart } = useMemo(() => {
    const scheduled = tasks
      .map((t) => {
        const start = parseDate(t.start_date) || parseDate(t.due_date);
        const end = parseDate(t.due_date) || parseDate(t.start_date);
        if (!start && !end) return null;
        const s = start || end!;
        const e = end && end >= s ? end : s;
        return { task: t, start: s, end: e };
      })
      .filter(Boolean) as { task: TaskInfo; start: Date; end: Date }[];

    if (scheduled.length === 0) {
      const today = new Date();
      const d0 = dayKey(today);
      return { days: [d0], bars: [], rangeStart: today };
    }

    let min = scheduled[0].start;
    let max = scheduled[0].end;
    for (const s of scheduled) {
      if (s.start < min) min = s.start;
      if (s.end > max) max = s.end;
    }
    min = addDays(min, -1);
    max = addDays(max, 2);
    const dayList: string[] = [];
    for (let d = new Date(min); d <= max; d = addDays(d, 1)) {
      dayList.push(dayKey(d));
    }
    const rs = new Date(min);
    const bars = scheduled.map(({ task, start, end }) => {
      const offset =
        Math.round((start.getTime() - rs.getTime()) / 86400000);
      const span = Math.max(
        1,
        Math.round((end.getTime() - start.getTime()) / 86400000) + 1
      );
      return { task, offset, span };
    });
    return { days: dayList, bars, rangeStart: rs };
  }, [tasks]);

  if (bars.length === 0) {
    return (
      <p className="rounded-xl border border-slate-800 bg-slate-900/40 p-8 text-center text-sm text-slate-500">
        暂无排期任务。为任务设置开始/截止日期后在此显示 Gantt 视图。
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800">
      <div className="min-w-[640px]">
        <div
          className="grid border-b border-slate-800 bg-slate-900/80 text-xs text-slate-400"
          style={{ gridTemplateColumns: `200px repeat(${days.length}, minmax(48px, 1fr))` }}
        >
          <div className="px-3 py-2">任务</div>
          {days.map((d) => (
            <div key={d} className="border-l border-slate-800/80 px-1 py-2 text-center">
              {d.slice(5)}
            </div>
          ))}
        </div>
        {bars.map(({ task, offset, span }) => (
          <div
            key={task.id}
            className="grid items-center border-t border-slate-800/60 py-2"
            style={{ gridTemplateColumns: `200px repeat(${days.length}, minmax(48px, 1fr))` }}
          >
            <div className="px-3">
              <Link
                href={wp.taskDetail(task.id)}
                className="text-sm text-indigo-300 hover:underline"
              >
                {truncate(task.prompt, 40)}
              </Link>
              <div className="mt-1">
                <StatusBadge status={task.status} />
              </div>
            </div>
            <div
              className="col-span-full grid"
              style={{
                gridColumn: `2 / -1`,
                gridTemplateColumns: `repeat(${days.length}, minmax(48px, 1fr))`,
              }}
            >
              <div
                className="mx-1 h-7 rounded-md bg-indigo-600/70"
                style={{
                  gridColumn: `${offset + 1} / span ${span}`,
                }}
                title={`${task.start_date || "?"} → ${task.due_date || "?"}`}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
