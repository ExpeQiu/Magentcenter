"use client";

import type { AutopilotInfo } from "@/lib/types";
import { StatusBadge, formatTime } from "@/components/ui/status-badge";
import {
  DOW_LABELS,
  groupByPeriod,
  type PeriodKind,
  type TimelineItem,
} from "./schedule-parse";

function sourceLabel(a: AutopilotInfo) {
  if (a.source === "hermes" || a.id.startsWith("hermes:")) return "Hermes";
  if (a.source === "openclaw" || a.id.startsWith("openclaw:")) return "OpenClaw";
  if (a.source === "bidirectional") return "双向";
  return "本地";
}

function runtimeLabel(a: AutopilotInfo) {
  return (
    a.runtime ||
    (a.id.startsWith("hermes:") ? "hermes" : "openclaw")
  ).toUpperCase();
}

function HourAxis({ items }: { items: TimelineItem[] }) {
  const placed = items.filter((i) => i.parsed.minuteOfDay != null);
  const unplaced = items.filter((i) => i.parsed.minuteOfDay == null);

  return (
    <div className="space-y-3">
      <div className="relative h-16 rounded-lg border border-slate-800 bg-slate-950/60">
        {/* 小时刻度 */}
        <div className="absolute inset-x-0 top-0 flex h-5 border-b border-slate-800/80 text-[10px] text-slate-600">
          {Array.from({ length: 24 }, (_, h) => (
            <div
              key={h}
              className="relative flex-1 border-l border-slate-800/60 first:border-l-0"
            >
              {(h % 3 === 0 || h === 23) && (
                <span className="absolute left-0.5 top-0.5">{String(h).padStart(2, "0")}</span>
              )}
            </div>
          ))}
        </div>
        {/* 任务点 */}
        <div className="absolute inset-x-2 bottom-2 top-6">
          {placed.map(({ autopilot: a, parsed }) => {
            const pct = ((parsed.minuteOfDay ?? 0) / 1440) * 100;
            return (
              <div
                key={a.id}
                className="group absolute top-1/2 max-w-[140px] -translate-x-1/2 -translate-y-1/2"
                style={{ left: `${pct}%` }}
                title={`${parsed.summary} · ${a.name}`}
              >
                <div className="mx-auto h-2.5 w-2.5 rounded-full bg-indigo-400 shadow shadow-indigo-500/40 ring-2 ring-slate-950" />
                <div className="pointer-events-none absolute left-1/2 top-4 z-10 hidden w-44 -translate-x-1/2 rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-[11px] text-slate-200 shadow-xl group-hover:block">
                  <p className="font-medium text-indigo-200">{parsed.summary}</p>
                  <p className="mt-0.5 truncate">{a.name}</p>
                  <p className="mt-0.5 text-slate-500">
                    {runtimeLabel(a)} · {sourceLabel(a)}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      {unplaced.length > 0 && (
        <p className="text-xs text-slate-500">
          {unplaced.length} 项无法定位到具体时刻（表达式含通配）
        </p>
      )}
    </div>
  );
}

function ItemRow({
  item,
  onTrigger,
  extra,
}: {
  item: TimelineItem;
  onTrigger: (id: string) => void;
  extra?: string;
}) {
  const { autopilot: a, parsed } = item;
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-800/80 px-3 py-2.5 text-sm first:border-t-0">
      <span className="w-16 shrink-0 font-mono text-xs text-indigo-300">
        {extra || parsed.summary.replace(/^(每日|每周.|每月 \d+ 日)\s*/, "") || "—"}
      </span>
      <span className="min-w-0 flex-1 truncate text-slate-200" title={a.name}>
        {a.name}
      </span>
      <span className="text-[10px] uppercase text-slate-500">{runtimeLabel(a)}</span>
      <span className="text-xs text-slate-500">{sourceLabel(a)}</span>
      <span className="hidden font-mono text-xs text-slate-600 sm:inline">
        {a.agent_id}
      </span>
      {a.status ? <StatusBadge status={a.status} /> : null}
      <span className="text-xs text-slate-600">
        {a.last_run ? formatTime(a.last_run) : "—"}
      </span>
      <button
        type="button"
        onClick={() => onTrigger(a.id)}
        className="text-xs text-indigo-400 hover:underline"
      >
        立即触发
      </button>
    </li>
  );
}

function WeeklyBoard({
  items,
  onTrigger,
}: {
  items: TimelineItem[];
  onTrigger: (id: string) => void;
}) {
  const byDow = Array.from({ length: 7 }, (_, d) =>
    items.filter((i) => i.parsed.dow === d)
  );
  // cron: 0=Sun … 展示顺序 一…日
  const order = [1, 2, 3, 4, 5, 6, 0];
  return (
    <div className="grid gap-2 md:grid-cols-7">
      {order.map((d) => (
        <div
          key={d}
          className="rounded-lg border border-slate-800 bg-slate-950/40"
        >
          <p className="border-b border-slate-800 px-2 py-1.5 text-center text-xs text-slate-400">
            周{DOW_LABELS[d]}
          </p>
          <ul className="max-h-96 min-h-64 space-y-1 overflow-y-auto p-1.5">
            {byDow[d].length === 0 ? (
              <li className="px-1 py-2 text-center text-[10px] text-slate-600">
                —
              </li>
            ) : (
              byDow[d].map((item) => (
                <li
                  key={item.autopilot.id}
                  className="rounded border border-slate-800/80 bg-slate-900/60 px-1.5 py-1"
                >
                  <p className="font-mono text-[10px] text-indigo-300">
                    {item.parsed.hour != null && item.parsed.minute != null
                      ? `${String(item.parsed.hour).padStart(2, "0")}:${String(item.parsed.minute).padStart(2, "0")}`
                      : "—"}
                  </p>
                  <p
                    className="truncate text-[11px] text-slate-200"
                    title={item.autopilot.name}
                  >
                    {item.autopilot.name}
                  </p>
                  <button
                    type="button"
                    onClick={() => onTrigger(item.autopilot.id)}
                    className="mt-0.5 text-[10px] text-indigo-400 hover:underline"
                  >
                    触发
                  </button>
                </li>
              ))
            )}
          </ul>
        </div>
      ))}
    </div>
  );
}

function PeriodBlock({
  kind,
  title,
  items,
  onTrigger,
}: {
  kind: PeriodKind;
  title: string;
  items: TimelineItem[];
  onTrigger: (id: string) => void;
}) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/40">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <h3 className="text-sm font-medium text-slate-200">
          {title}
          <span className="ml-2 text-xs font-normal text-slate-500">
            {items.length} 项
          </span>
        </h3>
      </div>
      <div className="space-y-3 p-4">
        {kind === "daily" && <HourAxis items={items} />}
        {kind === "weekly" && (
          <>
            <div className="hidden md:block">
              <WeeklyBoard items={items} onTrigger={onTrigger} />
            </div>
            <ul className="overflow-hidden rounded-lg border border-slate-800 md:hidden">
              {items.map((item) => (
                <ItemRow
                  key={item.autopilot.id}
                  item={item}
                  onTrigger={onTrigger}
                  extra={item.parsed.summary}
                />
              ))}
            </ul>
          </>
        )}
        {kind !== "weekly" && (
          <ul className="overflow-hidden rounded-lg border border-slate-800">
            {items.map((item) => {
              let extra = item.parsed.summary;
              if (kind === "daily" && item.parsed.hour != null) {
                extra = `${String(item.parsed.hour).padStart(2, "0")}:${String(item.parsed.minute ?? 0).padStart(2, "0")}`;
              } else if (kind === "monthly" && item.parsed.dom != null) {
                const hm =
                  item.parsed.hour != null
                    ? `${String(item.parsed.hour).padStart(2, "0")}:${String(item.parsed.minute ?? 0).padStart(2, "0")}`
                    : "";
                extra = `${item.parsed.dom}日 ${hm}`.trim();
              }
              return (
                <ItemRow
                  key={item.autopilot.id}
                  item={item}
                  onTrigger={onTrigger}
                  extra={extra}
                />
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}

interface TimelineViewProps {
  items: AutopilotInfo[];
  onTrigger: (id: string) => void;
}

export function TimelineView({ items, onTrigger }: TimelineViewProps) {
  const groups = groupByPeriod(items);
  if (groups.length === 0) return null;

  const now = new Date();
  const nowPct = ((now.getHours() * 60 + now.getMinutes()) / 1440) * 100;

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-800 bg-slate-900/30 px-4 py-3">
        <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
          <span>今日时间轴（当前时刻）</span>
          <span className="font-mono text-slate-400">
            {String(now.getHours()).padStart(2, "0")}:
            {String(now.getMinutes()).padStart(2, "0")}
          </span>
        </div>
        <div className="relative h-2 overflow-hidden rounded-full bg-slate-800">
          <div
            className="absolute inset-y-0 left-0 bg-indigo-500/30"
            style={{ width: `${nowPct}%` }}
          />
          <div
            className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 bg-indigo-300"
            style={{ left: `${nowPct}%` }}
          />
        </div>
      </div>
      {groups.map((g) => (
        <PeriodBlock
          key={g.kind}
          kind={g.kind}
          title={g.title}
          items={g.items}
          onTrigger={onTrigger}
        />
      ))}
    </div>
  );
}
