"use client";

import { useEffect, useRef, useState } from "react";
import type { KanbanTask } from "@/lib/types";
import { officeLog } from "@/components/kanban/office/office-log";
import {
  POSE_LABEL,
  tasksForActor,
  type OfficeActor,
  type OfficeGroup,
  type OfficePose,
} from "@/components/kanban/office/office-model";

const ZOOM_MIN = 0.55;
const ZOOM_MAX = 2.4;

type FigurePose = "sit" | "stand" | "walk";

function figureOf(pose: OfficePose): FigurePose {
  if (pose === "walking") return "walk";
  if (pose === "working" || pose === "talking") return "stand";
  return "sit";
}

function OfficePerson({
  pose,
  color,
  picked,
}: {
  pose: FigurePose;
  color: string;
  picked: boolean;
}) {
  const sitting = pose === "sit";
  return (
    <svg
      viewBox="0 0 36 48"
      data-office-figure={pose}
      className={`office-person h-[40px] w-[28px] ${picked ? "office-person-picked" : ""}`}
      aria-hidden
    >
      <ellipse cx="18" cy="46" rx="8" ry="1.7" fill="black" opacity="0.35" />
      {sitting && <rect x="8" y="28" width="20" height="3" rx="1" fill="#7a5a38" />}
      <circle cx="18" cy={sitting ? 14 : 8} r="5" fill="#f3d2b0" />
      <path
        d={sitting ? "M11 20c.3-2.4 2.4-3.8 7-3.8s6.7 1.4 7 3.8V29H11z" : "M11 14c.3-2 2.4-3.2 7-3.2s6.7 1.2 7 3.2V30H11z"}
        fill={color}
      />
      {sitting ? (
        <>
          <ellipse cx="12.5" cy="31" rx="4.2" ry="2.6" fill="#1e293b" />
          <ellipse cx="23.5" cy="31" rx="4.2" ry="2.6" fill="#1e293b" />
          <path className="office-leg" d="M10 32v8M14.5 33v8" />
          <path className="office-leg" d="M21.5 33v8M26 32v8" />
        </>
      ) : pose === "walk" ? (
        <>
          <line className="office-leg office-leg-a" x1="15" y1="30" x2="11" y2="43" />
          <line className="office-leg office-leg-b" x1="21" y1="30" x2="25" y2="43" />
        </>
      ) : (
        <>
          <line className="office-leg" x1="15" y1="30" x2="14" y2="44" />
          <line className="office-leg" x1="21" y1="30" x2="22" y2="44" />
        </>
      )}
    </svg>
  );
}

interface OfficeFloorProps {
  actors: OfficeActor[];
  groups: OfficeGroup[];
  tasks: KanbanTask[];
  selectedId: string | null;
  focusGroupId: string | null;
  preview: string;
  playing: boolean;
  asking: boolean;
  chat: string;
  onChat: (value: string) => void;
  onSend: () => void;
  onAsk: () => void;
  onSelect: (id: string) => void;
  onFocusGroup: (id: string | null) => void;
  onStop: () => void;
  onSummon: (id: string) => void;
}

export function OfficeFloor({
  actors,
  groups,
  tasks,
  selectedId,
  focusGroupId,
  preview,
  playing,
  asking,
  chat,
  onChat,
  onSend,
  onAsk,
  onSelect,
  onFocusGroup,
  onStop,
  onSummon,
}: OfficeFloorProps) {
  const roomRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const dragRef = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const talking = actors.filter((actor) => actor.pose === "talking").length;
  const moving = actors.filter((actor) => actor.pose === "walking").length;
  const selected = actors.find((actor) => actor.id === selectedId) || null;
  const selectedTasks = selected ? tasksForActor(tasks, selected) : [];
  const hint =
    talking > 0 ? `${talking} 人在说` : moving > 0 ? `${moving} 人在走` : "点一个人，或在下面说话";

  const setZoomClamped = (next: number) => {
    const value = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next));
    setZoom(value);
    officeLog("zoom", { zoom: Math.round(value * 100) });
    return value;
  };

  useEffect(() => {
    const room = roomRef.current;
    if (!room) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = room.getBoundingClientRect();
      const mx = event.clientX - rect.left - rect.width / 2;
      const my = event.clientY - rect.top - rect.height / 2;
      setZoom((current) => {
        const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, current * (event.deltaY > 0 ? 0.92 : 1.08)));
        const ratio = next / current;
        setPan((prev) => ({
          x: mx - (mx - prev.x) * ratio,
          y: my - (my - prev.y) * ratio,
        }));
        return next;
      });
    };
    room.addEventListener("wheel", onWheel, { passive: false });
    return () => room.removeEventListener("wheel", onWheel);
  }, []);

  const groupKey = groups.map((group) => `${group.id}:${group.x}:${group.y}`).join("|");
  const focusWas = useRef<string | null>(null);
  useEffect(() => {
    const room = roomRef.current;
    if (!room) return;
    if (!focusGroupId) {
      if (focusWas.current) {
        setZoom(1);
        setPan({ x: 0, y: 0 });
      }
      focusWas.current = null;
      return;
    }
    const group = groups.find((item) => item.id === focusGroupId);
    focusWas.current = focusGroupId;
    if (!group) return;
    const next = 1.7;
    const cx = group.x + group.w / 2;
    const cy = group.y + group.h / 2;
    setZoom(next);
    setPan({
      x: -((cx - 50) / 100) * room.clientWidth * next,
      y: -((cy - 50) / 100) * room.clientHeight * next,
    });
    officeLog("zoom_group", { group_id: group.id, zoom: Math.round(next * 100) });
  }, [focusGroupId, groupKey, groups]);

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-800 bg-[#0d141d] shadow-[0_20px_50px_-24px_rgba(0,0,0,0.7)]">
      <div className="flex items-center justify-between gap-3 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] ${
              playing ? "bg-indigo-500/20 text-indigo-100" : "bg-slate-800/80 text-slate-400"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${playing ? "bg-indigo-300" : "bg-slate-500"}`}
            />
            {playing ? "演示中" : "待命"}
          </span>
          <p className="text-[11px] text-slate-500">{hint}</p>
        </div>
        {playing && (
          <button
            type="button"
            onClick={onStop}
            className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-200 hover:bg-slate-800"
          >
            暂停
          </button>
        )}
      </div>

      <div
        ref={roomRef}
        className="office-room relative mx-3 mb-1 aspect-square w-full cursor-grab overflow-hidden rounded-xl border border-slate-800/80 active:cursor-grabbing"
        onPointerDown={(event) => {
          if ((event.target as HTMLElement).closest("button")) return;
          dragRef.current = {
            x: event.clientX,
            y: event.clientY,
            panX: pan.x,
            panY: pan.y,
          };
          (event.currentTarget as HTMLDivElement).setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current;
          if (!drag) return;
          setPan({
            x: drag.panX + event.clientX - drag.x,
            y: drag.panY + event.clientY - drag.y,
          });
        }}
        onPointerUp={() => {
          dragRef.current = null;
        }}
        onPointerCancel={() => {
          dragRef.current = null;
        }}
      >
        <div
          className="absolute inset-0"
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: "center center",
          }}
        >
        <div className="pointer-events-none absolute inset-x-0 top-0 h-[14%] bg-gradient-to-b from-[#243246] to-[#1a2636]" />
        <div className="pointer-events-none absolute inset-x-0 top-[14%] h-px bg-slate-700/40" />
        <div className="office-floor-plane pointer-events-none absolute inset-x-0 bottom-0 top-[14%]" />

        <div className="pointer-events-none absolute left-[2%] top-[1.5%] h-9 w-20 overflow-hidden rounded-md border border-sky-800/60 bg-gradient-to-b from-sky-400/35 via-sky-700/25 to-slate-900/40 shadow-inner">
          <div className="absolute inset-y-1 left-1/2 w-px bg-sky-950/70" />
          <div className="absolute inset-x-1 top-1/2 h-px bg-sky-950/70" />
        </div>

        <div className="pointer-events-none absolute right-[2%] top-[1%] h-[12%] w-[18%] max-w-[128px] overflow-hidden">
          <div className="rounded-md border-[5px] border-[#d7dee8] bg-[#f4f7fb] px-2.5 py-2 shadow-[0_10px_24px_-12px_rgba(0,0,0,0.8)]">
            <p className="text-[10px] font-medium tracking-wide text-slate-400">白板</p>
            <p className="mt-1 line-clamp-3 min-h-[2.4rem] text-[11px] leading-snug text-slate-700">
              {preview || "还没有人写字"}
            </p>
          </div>
          <div className="mx-auto h-2 w-16 rounded-b bg-slate-600/80" />
        </div>

        {groups.map((group) => {
          const quiet = Boolean(focusGroupId) && focusGroupId !== group.id;
          return (
            <button
              key={group.id}
              type="button"
              onClick={() => onFocusGroup(focusGroupId === group.id ? null : group.id)}
              className={`absolute rounded-xl border text-left ${quiet ? "opacity-30" : ""}`}
              style={{
                left: `${group.x}%`,
                top: `${group.y}%`,
                width: `${group.w}%`,
                height: `${group.h}%`,
                borderColor: group.color,
                background: `${group.color}14`,
              }}
            >
              <span className="absolute left-1.5 top-1 truncate text-[10px] font-medium" style={{ color: group.color }}>
                {group.name}
                {group.leaderName ? ` · ${group.leaderName}` : ""}
              </span>
              <span className="absolute right-1.5 top-1 text-[9px] text-slate-500">{group.count} 人</span>
            </button>
          );
        })}

        <svg className="pointer-events-none absolute inset-0 z-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
          {actors
            .filter((actor) => !actor.lead)
            .map((actor) => {
              const leader = actors.find((item) => item.groupId === actor.groupId && item.lead);
              if (!leader) return null;
              const quiet = Boolean(focusGroupId) && focusGroupId !== actor.groupId;
              return (
                <line
                  key={`link-${actor.id}`}
                  x1={leader.homeX}
                  y1={leader.homeY}
                  x2={actor.homeX}
                  y2={actor.homeY}
                  stroke={actor.accent}
                  strokeWidth="0.28"
                  strokeOpacity={quiet ? 0.12 : 0.45}
                />
              );
            })}
        </svg>

        {actors.map((actor) => {
          const mine = tasksForActor(tasks, actor);
          const away =
            Math.abs(actor.x - actor.homeX) > 3 || Math.abs(actor.y - actor.homeY) > 3;
          const active = selectedId === actor.id;
          const quiet = Boolean(focusGroupId) && focusGroupId !== actor.groupId;
          return (
            <button
              key={`desk-${actor.id}`}
              type="button"
              onClick={() => onSelect(actor.id)}
              className={`absolute z-[1] -translate-x-1/2 -translate-y-1/2 border-0 bg-transparent p-0 ${
                active ? "z-20" : ""
              } ${quiet ? "opacity-30" : ""}`}
              style={{ left: `${actor.deskX}%`, top: `${actor.deskY}%` }}
              title={mine[0] ? `${actor.name} · ${mine[0].title}` : `${actor.groupName} · ${actor.name}`}
            >
              <span
                className={`relative block h-[28px] w-[52px] ${
                  !away && actor.pose === "working" ? "office-desk-live" : ""
                }`}
              >
                <span className="absolute left-1/2 top-0 h-3.5 w-6 -translate-x-1/2 rounded-sm bg-slate-950 shadow-md ring-1 ring-slate-500/70">
                  <span className="absolute inset-0.5 rounded-[1px] bg-gradient-to-b from-sky-700/80 to-slate-900" />
                </span>
                <span className="absolute left-1/2 top-[13px] h-1 w-2 -translate-x-1/2 rounded-sm bg-slate-500" />
                <span
                  className={`absolute inset-x-0.5 bottom-0 h-2 rounded-sm bg-gradient-to-b from-[#c4a06a] to-[#7a5a38] ${
                    active ? "ring-1 ring-white/70" : ""
                  }`}
                />
                <span className="absolute inset-x-0 top-[calc(100%+1px)] truncate text-center text-[9px] leading-none text-slate-300">
                  {actor.name}
                </span>
              </span>
            </button>
          );
        })}

        {actors.map((actor) => {
          const picked = selectedId === actor.id;
          const away =
            Math.abs(actor.x - actor.homeX) > 3 || Math.abs(actor.y - actor.homeY) > 3;
          const pose =
            away && actor.pose === "idle" ? "在场" : actor.pose === "idle" ? "" : POSE_LABEL[actor.pose];
          const quiet = Boolean(focusGroupId) && focusGroupId !== actor.groupId;
          return (
            <button
              key={actor.id}
              type="button"
              data-office-agent={actor.id}
              data-office-group={actor.groupId}
              data-office-pose={actor.pose}
              onClick={() => onSelect(actor.id)}
              aria-label={actor.name}
              className={`office-actor absolute z-10 border-0 bg-transparent p-0 ${
                actor.pose === "walking" ? "office-bob" : ""
              } ${actor.pose === "talking" ? "office-talk" : ""} ${quiet ? "opacity-30" : ""}`}
              style={{ left: `${actor.x}%`, top: `${actor.y}%` }}
            >
              {actor.bubble && (
                <span className="office-bubble absolute bottom-[calc(100%+8px)] left-1/2 z-20 w-max max-w-[180px] -translate-x-1/2 whitespace-nowrap rounded-xl bg-white px-2.5 py-1 text-[11px] text-slate-800 shadow-lg">
                  {actor.bubble}
                </span>
              )}
              <span className="relative flex flex-col items-center">
                <OfficePerson pose={figureOf(actor.pose)} color={actor.accent} picked={picked} />
                {pose && (
                  <span className="mt-1 rounded-full bg-slate-950/75 px-1.5 py-px text-[10px] text-slate-300">
                    {pose}
                  </span>
                )}
                {away && (
                  <span className="mt-0.5 max-w-[72px] truncate text-[10px] text-slate-200">
                    {actor.name}
                  </span>
                )}
              </span>
            </button>
          );
        })}
        </div>

        {selected && (
          <div className="absolute left-3 top-3 z-30 w-44 rounded-xl border border-white/10 bg-slate-950/80 p-3 shadow-xl backdrop-blur-md">
            <p className="truncate text-sm text-slate-100">
              {selected.emoji ? `${selected.emoji} ` : ""}
              {selected.name}
            </p>
            <p className="mt-1 text-[11px] text-slate-400">
              {selected.groupName || "未编组"}
              {selected.lead ? " · 队长" : selected.groupName ? " · 成员" : ""}
            </p>
            {selected.alsoIn.length > 0 && (
              <p className="mt-1 text-[11px] text-slate-500">另属 {selected.alsoIn.join("、")}</p>
            )}
            <p className="mt-1 text-[11px] text-slate-400">
              {POSE_LABEL[selected.pose]}
              {selected.runtime ? ` · ${selected.runtime}` : ""}
            </p>
            <p className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-slate-500">
              {selectedTasks[0]?.title || "这个工位还没有任务"}
            </p>
            <button
              type="button"
              onClick={() => onSummon(selected.id)}
              className="mt-2 text-[11px] text-sky-300 hover:underline"
            >
              叫到白板
            </button>
          </div>
        )}

        {actors.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="rounded-xl bg-slate-950/75 px-4 py-3 text-sm text-slate-400">
              还没有 Agent
            </p>
          </div>
        )}

        <div className="absolute bottom-2 right-2 z-30 flex items-center gap-1 rounded-full border border-slate-700/80 bg-slate-950/80 p-1 backdrop-blur-md">
          <button
            type="button"
            aria-label="缩小"
            onClick={() => setZoomClamped(zoom - 0.15)}
            className="flex h-7 w-7 items-center justify-center rounded-full text-sm text-slate-200 hover:bg-slate-800"
          >
            −
          </button>
          <span className="w-10 text-center text-[10px] tabular-nums text-slate-400">
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            aria-label="放大"
            onClick={() => setZoomClamped(zoom + 0.15)}
            className="flex h-7 w-7 items-center justify-center rounded-full text-sm text-slate-200 hover:bg-slate-800"
          >
            +
          </button>
          <button
            type="button"
            aria-label="适应"
            onClick={() => {
              setZoom(1);
              setPan({ x: 0, y: 0 });
              onFocusGroup(null);
              officeLog("zoom", { zoom: 100 });
            }}
            className="rounded-full px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800"
          >
            适应
          </button>
        </div>
      </div>

      <form
        className="flex items-center gap-2 px-3 py-3"
        onSubmit={(event) => {
          event.preventDefault();
          onSend();
        }}
      >
        <input
          value={chat}
          onChange={(event) => onChat(event.target.value)}
          placeholder="和办公室聊一聊…"
          className="min-w-0 flex-1 rounded-full border border-slate-700/80 bg-slate-900/80 px-4 py-2 text-sm outline-none placeholder:text-slate-500 focus:border-indigo-400"
        />
        <button
          type="button"
          onClick={onAsk}
          disabled={asking || playing || !chat.trim()}
          className="shrink-0 rounded-full border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40"
        >
          {asking ? "在问…" : "问超级AI"}
        </button>
        <button
          type="submit"
          disabled={playing || !chat.trim()}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-500 text-sm text-white shadow-md shadow-indigo-950/40 disabled:opacity-40"
          aria-label="发送"
        >
          ↑
        </button>
      </form>
    </section>
  );
}
