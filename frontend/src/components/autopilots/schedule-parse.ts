import type { AutopilotInfo } from "@/lib/types";

export type PeriodKind =
  | "hourly"
  | "daily"
  | "weekly"
  | "monthly"
  | "interval"
  | "custom";

export interface ParsedSchedule {
  period: PeriodKind;
  periodLabel: string;
  /** 当日分钟数 0–1439；无法解析则为 null */
  minuteOfDay: number | null;
  hour: number | null;
  minute: number | null;
  /** 0=周日 … 6=周六（cron 惯例） */
  dow: number | null;
  dom: number | null;
  raw: string;
  summary: string;
}

const DOW_LABELS = ["日", "一", "二", "三", "四", "五", "六"];

const PERIOD_ORDER: PeriodKind[] = [
  "daily",
  "weekly",
  "monthly",
  "hourly",
  "interval",
  "custom",
];

const PERIOD_TITLE: Record<PeriodKind, string> = {
  daily: "每日",
  weekly: "每周",
  monthly: "每月",
  hourly: "每小时",
  interval: "固定间隔",
  custom: "其他",
};

function stripTz(expr: string): string {
  return expr.replace(/@[\w/+-]+/g, "").trim();
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

function fmtHm(h: number, m: number): string {
  return `${pad2(h)}:${pad2(m)}`;
}

/** 解析 cron / 间隔 / hourly|daily 等调度串 */
export function parseSchedule(raw: string | undefined | null): ParsedSchedule {
  const original = (raw || "").trim();
  const base: ParsedSchedule = {
    period: "custom",
    periodLabel: PERIOD_TITLE.custom,
    minuteOfDay: null,
    hour: null,
    minute: null,
    dow: null,
    dom: null,
    raw: original || "—",
    summary: original || "—",
  };
  if (!original) return base;

  const lower = original.toLowerCase();
  if (lower === "hourly" || lower === "hour") {
    return {
      ...base,
      period: "hourly",
      periodLabel: PERIOD_TITLE.hourly,
      summary: "每小时",
    };
  }
  if (lower === "daily" || lower === "day") {
    return {
      ...base,
      period: "daily",
      periodLabel: PERIOD_TITLE.daily,
      hour: 0,
      minute: 0,
      minuteOfDay: 0,
      summary: "每日 00:00",
    };
  }

  // 纯数字：间隔秒
  if (/^\d+$/.test(original)) {
    const sec = Number(original);
    const summary =
      sec >= 86400
        ? `每 ${Math.round(sec / 86400)} 天`
        : sec >= 3600
          ? `每 ${Math.round(sec / 3600)} 小时`
          : sec >= 60
            ? `每 ${Math.round(sec / 60)} 分钟`
            : `每 ${sec} 秒`;
    const period: PeriodKind =
      sec > 0 && sec < 3600 * 2 && 3600 % sec === 0 ? "hourly" : "interval";
    return {
      ...base,
      period,
      periodLabel: PERIOD_TITLE[period],
      summary,
    };
  }

  const expr = stripTz(original);
  const parts = expr.split(/\s+/).filter(Boolean);
  // 支持 5 段或 6 段（含秒）
  let minuteStr: string;
  let hourStr: string;
  let domStr: string;
  let monthStr: string;
  let dowStr: string;
  if (parts.length >= 6) {
    [, minuteStr, hourStr, domStr, monthStr, dowStr] = parts;
  } else if (parts.length >= 5) {
    [minuteStr, hourStr, domStr, monthStr, dowStr] = parts;
  } else {
    return { ...base, summary: original };
  }

  const minute = /^\d+$/.test(minuteStr) ? Number(minuteStr) : null;
  const hour = /^\d+$/.test(hourStr) ? Number(hourStr) : null;
  const dom = /^\d+$/.test(domStr) ? Number(domStr) : null;
  const dow = /^\d+$/.test(dowStr) ? Number(dowStr) % 7 : null;
  const monthStar = monthStr === "*";
  const domStar = domStr === "*";
  const dowStar = dowStr === "*" || dowStr === "?";

  let period: PeriodKind = "custom";
  if (monthStar && domStar && dowStar && hour !== null && minute !== null) {
    period = "daily";
  } else if (monthStar && domStar && !dowStar && hour !== null && minute !== null) {
    period = "weekly";
  } else if (monthStar && !domStar && dowStar && hour !== null && minute !== null) {
    period = "monthly";
  } else if (monthStar && domStar && dowStar && hourStr === "*" && minute !== null) {
    period = "hourly";
  }

  const minuteOfDay =
    hour !== null && minute !== null ? hour * 60 + minute : null;

  let summary = original;
  if (period === "daily" && hour !== null && minute !== null) {
    summary = `每日 ${fmtHm(hour, minute)}`;
  } else if (period === "weekly" && dow !== null && hour !== null && minute !== null) {
    summary = `每周${DOW_LABELS[dow]} ${fmtHm(hour, minute)}`;
  } else if (period === "monthly" && dom !== null && hour !== null && minute !== null) {
    summary = `每月 ${dom} 日 ${fmtHm(hour, minute)}`;
  } else if (period === "hourly" && minute !== null) {
    summary = `每小时 :${pad2(minute)}`;
  }

  return {
    period,
    periodLabel: PERIOD_TITLE[period],
    minuteOfDay,
    hour,
    minute,
    dow,
    dom,
    raw: original,
    summary,
  };
}

export interface TimelineItem {
  autopilot: AutopilotInfo;
  parsed: ParsedSchedule;
}

export function groupByPeriod(items: AutopilotInfo[]): {
  kind: PeriodKind;
  title: string;
  items: TimelineItem[];
}[] {
  const map = new Map<PeriodKind, TimelineItem[]>();
  for (const a of items) {
    const parsed = parseSchedule(a.schedule || a.cron);
    const list = map.get(parsed.period) || [];
    list.push({ autopilot: a, parsed });
    map.set(parsed.period, list);
  }
  for (const list of map.values()) {
    list.sort((a, b) => {
      const am = a.parsed.minuteOfDay ?? 99999;
      const bm = b.parsed.minuteOfDay ?? 99999;
      if (am !== bm) return am - bm;
      const ad = a.parsed.dow ?? a.parsed.dom ?? 0;
      const bd = b.parsed.dow ?? b.parsed.dom ?? 0;
      if (ad !== bd) return ad - bd;
      return a.autopilot.name.localeCompare(b.autopilot.name, "zh");
    });
  }
  return PERIOD_ORDER.filter((k) => map.has(k)).map((kind) => ({
    kind,
    title: PERIOD_TITLE[kind],
    items: map.get(kind)!,
  }));
}

export { DOW_LABELS, PERIOD_TITLE };
