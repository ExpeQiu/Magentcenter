"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { FleetAgent, FleetLink, FleetNode, FleetScan } from "@/lib/types";

const VB_W = 1400;
const VB_H = 900;
const CX = 700;
const CY = 450;

export interface FleetGraphItem {
  id: string;
  kind: "cloud" | "device" | "agent";
  source: "cloud" | "node" | "peer" | "scan" | "agent";
  parentId: string;
  parentLabel: string;
  label: string;
  detail: string;
  hostname: string;
  online: boolean;
  bound: boolean;
  local: boolean;
  runtime: string;
  model: string;
  agentKey: string;
  agentCount: number;
  capabilities: string[];
}

interface BuildInput {
  link: FleetLink | null;
  nodes: FleetNode[];
  scan: FleetScan | null;
  localPicked: string[];
  picked: Record<string, string[]>;
  preferId?: string;
}

interface Pos {
  x: number;
  y: number;
  r: number;
  labelX: number;
  labelY: number;
  anchor: "start" | "end" | "middle";
}

function agentKey(agent: FleetAgent) {
  return `${agent.runtime}:${agent.id}`;
}

function hostOf(url: string) {
  const raw = url.trim();
  if (!raw) return "未填写地址";
  try {
    return new URL(raw).host;
  } catch {
    return raw.replace(/^https?:\/\//, "");
  }
}

function short(text: string, max: number) {
  const value = text.trim();
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1)}…`;
}

export function buildFleetGraph(input: BuildInput): FleetGraphItem[] {
  const { link, nodes, scan, localPicked, picked, preferId } = input;
  const cloudOnline = link?.state === "ok";
  const cloud: FleetGraphItem = {
    id: "cloud",
    kind: "cloud",
    source: "cloud",
    parentId: "",
    parentLabel: "",
    label: link?.local_cloud ? "协调器" : "云端",
    detail: link?.local_cloud ? "本机协调器" : hostOf(link?.cloud_url || ""),
    hostname: link?.cloud_url || "",
    online: cloudOnline,
    bound: Boolean(link?.bound),
    local: Boolean(link?.local_cloud),
    runtime: "",
    model: "",
    agentKey: "",
    agentCount: 0,
    capabilities: link?.capabilities || [],
  };

  type Seed = {
    id: string;
    source: FleetGraphItem["source"];
    name: string;
    hostname: string;
    local: boolean;
    online: boolean;
    bound: boolean;
    capabilities: string[];
    agents: { agent: FleetAgent; bound: boolean }[];
  };

  const seeds: Seed[] = [];
  const seen = new Set<string>();

  const poolFor = (node: FleetNode) => {
    if (scan && scan.node_id === node.id && scan.agents.length) return scan.agents;
    if (node.seen.length) return node.seen;
    return node.agents;
  };

  const boundFor = (node: FleetNode, agent: FleetAgent) => {
    const key = agentKey(agent);
    if (scan && scan.node_id === node.id) return localPicked.includes(key);
    const keys = picked[node.id];
    if (keys) return keys.includes(key);
    return node.agents.some((item) => agentKey(item) === key);
  };

  for (const node of nodes) {
    seen.add(node.id);
    const local = node.mode === "local" || node.id === link?.node_id;
    seeds.push({
      id: node.id,
      source: "node",
      name: node.name || node.hostname || node.id,
      hostname: node.hostname || node.id,
      local,
      online: node.online,
      bound: node.bound,
      capabilities: node.capabilities?.length ? node.capabilities : node.runtimes,
      agents: poolFor(node).map((agent) => ({ agent, bound: boundFor(node, agent) })),
    });
  }

  if (link?.state === "ok" && link.node_id && !seen.has(link.node_id)) {
    seen.add(link.node_id);
    seeds.push({
      id: link.node_id,
      source: "node",
      name: "本机",
      hostname: link.node_id,
      local: true,
      online: true,
      bound: link.bound,
      capabilities: link.capabilities || [],
      agents: link.agents.map((agent) => ({ agent, bound: true })),
    });
  }

  if (scan && !seen.has(scan.node_id)) {
    seen.add(scan.node_id);
    seeds.push({
      id: scan.node_id,
      source: "scan",
      name: scan.name || scan.hostname || "本机",
      hostname: scan.hostname || scan.node_id,
      local: true,
      online: true,
      bound: false,
      capabilities: [],
      agents: scan.agents.map((agent) => ({
        agent,
        bound: localPicked.includes(agentKey(agent)),
      })),
    });
  }

  for (const peer of link?.peers || []) {
    if (seen.has(peer.id)) continue;
    seen.add(peer.id);
    const caps = peer.capabilities.length ? peer.capabilities : peer.runtimes;
    seeds.push({
      id: peer.id,
      source: "peer",
      name: peer.name || peer.hostname || peer.id,
      hostname: peer.hostname || peer.id,
      local: false,
      online: peer.online,
      bound: true,
      capabilities: caps,
      agents: peer.agents.map((agent) => ({ agent, bound: true })),
    });
  }

  seeds.sort((a, b) => {
    if (a.local !== b.local) return a.local ? -1 : 1;
    const aPrefer = a.id === preferId;
    const bPrefer = b.id === preferId;
    if (aPrefer !== bPrefer) return aPrefer ? -1 : 1;
    if (a.online !== b.online) return a.online ? -1 : 1;
    return a.name.localeCompare(b.name, "zh");
  });

  const items: FleetGraphItem[] = [cloud];
  for (const seed of seeds) {
    items.push({
      id: seed.id,
      kind: "device",
      source: seed.source,
      parentId: cloud.id,
      parentLabel: cloud.label,
      label: seed.name,
      detail: seed.hostname,
      hostname: seed.hostname,
      online: seed.online,
      bound: seed.bound,
      local: seed.local,
      runtime: "",
      model: "",
      agentKey: "",
      agentCount: seed.agents.length,
      capabilities: seed.capabilities,
    });
    for (const entry of seed.agents) {
      const key = agentKey(entry.agent);
      items.push({
        id: `${seed.id}::${key}`,
        kind: "agent",
        source: "agent",
        parentId: seed.id,
        parentLabel: seed.name,
        label: entry.agent.name || key,
        detail: entry.agent.model
          ? `${entry.agent.runtime} · ${entry.agent.model}`
          : entry.agent.runtime,
        hostname: "",
        online: seed.online,
        bound: entry.bound,
        local: seed.local,
        runtime: entry.agent.runtime,
        model: entry.agent.model || "",
        agentKey: key,
        agentCount: 0,
        capabilities: [],
      });
    }
  }

  cloud.agentCount = items.filter((item) => item.kind === "agent").length;
  return items;
}

function layout(items: FleetGraphItem[], focusId: string): {
  pos: Map<string, Pos>;
  edges: { from: string; to: string }[];
  sector: { d: string; local: boolean } | null;
  deviceCount: number;
} {
  const pos = new Map<string, Pos>();
  pos.set("cloud", {
    x: CX,
    y: CY,
    r: 46,
    labelX: CX,
    labelY: CY,
    anchor: "middle",
  });

  const devices = items.filter((item) => item.kind === "device");
  const n = devices.length;
  const edges: { from: string; to: string }[] = [];
  let sector: { d: string; local: boolean } | null = null;

  devices.forEach((device, index) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * index) / Math.max(n, 1);
    const focused = device.id === focusId;
    const dist = n === 1 ? 240 : 268;
    const x = CX + Math.cos(angle) * dist;
    const y = CY + Math.sin(angle) * dist;
    const r = focused ? 30 : 26;
    const perpX = -Math.sin(angle);
    const inwardX = (CX - x) / dist;
    const inwardY = (CY - y) / dist;
    pos.set(device.id, {
      x,
      y,
      r,
      labelX: x + inwardX * (r + 36) + perpX * 64,
      labelY: y + inwardY * (r + 18),
      anchor: perpX >= 0 ? "start" : "end",
    });
    edges.push({ from: "cloud", to: device.id });

    const agents = items.filter((item) => item.kind === "agent" && item.parentId === device.id);
    if (!agents.length) return;
    const sectorSpan = ((2 * Math.PI) / Math.max(n, 1)) * (focused ? 0.86 : 0.7);
    const span = n === 1 ? Math.PI * 1.55 : sectorSpan;
    const minStep = focused ? 0.085 : 0.11;
    const perRing = Math.max(1, Math.floor(span / minStep));
    const startR = dist + (focused ? 78 : 64);
    const gap = focused ? 26 : 18;
    let outer = startR;

    agents.forEach((agent, agentIndex) => {
      const ring = Math.floor(agentIndex / perRing);
      const indexInRing = agentIndex % perRing;
      const inRing = Math.min(perRing, agents.length - ring * perRing);
      const t = inRing === 1 ? 0.5 : indexInRing / (inRing - 1);
      const ang = angle - span / 2 + t * span;
      const rad = startR + ring * gap;
      outer = Math.max(outer, rad);
      const ax = CX + Math.cos(ang) * rad;
      const ay = CY + Math.sin(ang) * rad;
      pos.set(agent.id, {
        x: ax,
        y: ay,
        r: focused ? 6.5 : 4.2,
        labelX: ax + Math.cos(ang) * 12,
        labelY: ay + Math.sin(ang) * 12,
        anchor: Math.cos(ang) >= 0 ? "start" : "end",
      });
      edges.push({ from: device.id, to: agent.id });
    });

    if (focused) {
      const r0 = dist + 40;
      const r1 = outer + 18;
      const a0 = angle - span / 2 - 0.06;
      const a1 = angle + span / 2 + 0.06;
      const arc = (radius: number, a: number) =>
        `${CX + Math.cos(a) * radius} ${CY + Math.sin(a) * radius}`;
      const large = a1 - a0 > Math.PI ? 1 : 0;
      sector = {
        local: device.local,
        d: `M ${arc(r0, a0)} A ${r0} ${r0} 0 ${large} 1 ${arc(r0, a1)} L ${arc(r1, a1)} A ${r1} ${r1} 0 ${large} 0 ${arc(r1, a0)} Z`,
      };
    }
  });

  return { pos, edges, sector, deviceCount: n };
}

function agentFill(item: FleetGraphItem) {
  if (item.runtime === "hermes") return "#fbbf24";
  if (item.runtime === "openclaw") return "#38bdf8";
  return "#cbd5e1";
}

function matches(item: FleetGraphItem, query: string) {
  if (!query) return true;
  const hay = `${item.label} ${item.detail} ${item.runtime} ${item.model} ${item.parentLabel}`.toLowerCase();
  return hay.includes(query);
}

interface FleetGraphProps {
  items: FleetGraphItem[];
  selectedId: string;
  query: string;
  onSelect: (item: FleetGraphItem) => void;
}

export function FleetGraph({ items, selectedId, query, onSelect }: FleetGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const camRef = useRef({ x: 0, y: 0, k: 1 });
  const [cam, setCam] = useState({ x: 0, y: 0, k: 1 });
  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null);
  const drag = useRef<{
    x: number;
    y: number;
    camx: number;
    camy: number;
    moved: boolean;
  } | null>(null);

  const selected = items.find((item) => item.id === selectedId) || null;
  const focusId =
    selected?.kind === "device" ? selected.id : selected?.kind === "agent" ? selected.parentId : "";
  const q = query.trim().toLowerCase();
  const graph = useMemo(() => layout(items, focusId), [items, focusId]);
  const hoverItem = hover ? items.find((item) => item.id === hover.id) : null;

  useEffect(() => {
    camRef.current = cam;
  }, [cam]);

  useEffect(() => {
    const el = boxRef.current;
    const svg = svgRef.current;
    if (!el || !svg) return;

    const toVb = (clientX: number, clientY: number) => {
      const point = svg.createSVGPoint();
      point.x = clientX;
      point.y = clientY;
      const matrix = svg.getScreenCTM();
      if (!matrix) return { x: 0, y: 0 };
      const mapped = point.matrixTransform(matrix.inverse());
      return { x: mapped.x, y: mapped.y };
    };

    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const cursor = toVb(event.clientX, event.clientY);
      const factor = event.deltaY < 0 ? 1.08 : 0.92;
      setCam((current) => {
        const k = Math.min(2.8, Math.max(0.45, current.k * factor));
        const worldX = (cursor.x - current.x) / current.k;
        const worldY = (cursor.y - current.y) / current.k;
        return { k, x: cursor.x - worldX * k, y: cursor.y - worldY * k };
      });
    };

    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const placeTip = (id: string, event: React.PointerEvent) => {
    const box = boxRef.current?.getBoundingClientRect();
    if (!box) return;
    let x = event.clientX - box.left + 14;
    let y = event.clientY - box.top + 14;
    if (x > box.width - 240) x = event.clientX - box.left - 230;
    if (y > box.height - 80) y = event.clientY - box.top - 72;
    setHover({ id, x, y });
  };

  const onPointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    if ((event.target as Element).closest("[data-node]")) return;
    drag.current = {
      x: event.clientX,
      y: event.clientY,
      camx: camRef.current.x,
      camy: camRef.current.y,
      moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    const current = drag.current;
    if (!svg || !current) return;
    const dx = event.clientX - current.x;
    const dy = event.clientY - current.y;
    if (Math.hypot(dx, dy) > 3) current.moved = true;
    const point = svg.createSVGPoint();
    const matrix = svg.getScreenCTM();
    if (!matrix) return;
    point.x = event.clientX;
    point.y = event.clientY;
    const now = point.matrixTransform(matrix.inverse());
    point.x = current.x;
    point.y = current.y;
    const start = point.matrixTransform(matrix.inverse());
    setCam({
      x: current.camx + (now.x - start.x),
      y: current.camy + (now.y - start.y),
      k: camRef.current.k,
    });
  };

  const endDrag = () => {
    drag.current = null;
  };

  const zoomBy = (factor: number) => {
    setCam((current) => {
      const k = Math.min(2.8, Math.max(0.45, current.k * factor));
      const worldX = (CX - current.x) / current.k;
      const worldY = (CY - current.y) / current.k;
      return { k, x: CX - worldX * k, y: CY - worldY * k };
    });
  };

  const edgeEnds = (from: string, to: string) => {
    const a = graph.pos.get(from);
    const b = graph.pos.get(to);
    if (!a || !b) return null;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    return {
      x1: a.x + (dx / len) * (a.r + 2),
      y1: a.y + (dy / len) * (a.r + 2),
      x2: b.x - (dx / len) * (b.r + 2),
      y2: b.y - (dy / len) * (b.r + 2),
    };
  };

  const edgeAlpha = (from: string, to: string) => {
    if (!selected || selected.kind === "cloud") return from === "cloud" ? 0.85 : 0.45;
    if (selected.kind === "device") {
      return from === selected.id || to === selected.id ? 0.95 : 0.16;
    }
    return to === selected.id || to === selected.parentId || (from === "cloud" && to === selected.parentId)
      ? 1
      : 0.12;
  };

  const nodeAlpha = (item: FleetGraphItem) => {
    const self = matches(item, q);
    if (q && item.kind === "agent" && !self) return 0.12;
    if (q && item.kind === "device") {
      const childHit = items.some(
        (child) => child.parentId === item.id && child.kind === "agent" && matches(child, q)
      );
      if (!self && !childHit) return 0.2;
    }
    if (!selected || selected.kind === "cloud") return 1;
    if (item.id === selected.id || item.id === selected.parentId || item.parentId === selected.id) return 1;
    if (selected.kind === "agent" && (item.id === "cloud" || item.parentId === selected.parentId)) return 1;
    return 0.28;
  };

  return (
    <div
      ref={boxRef}
      className="relative h-[calc(100svh-14rem)] min-h-[540px] overflow-hidden rounded-2xl border border-slate-800 bg-slate-950"
    >
      <svg
        ref={svgRef}
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        className="h-full w-full touch-none select-none"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <defs>
          <radialGradient id="fleet-bg" cx="50%" cy="50%" r="65%">
            <stop offset="0%" stopColor="#0f172a" />
            <stop offset="70%" stopColor="#020617" />
            <stop offset="100%" stopColor="#020617" />
          </radialGradient>
          <pattern id="fleet-dots" width="28" height="28" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="1" fill="#1e293b" />
          </pattern>
          <filter id="fleet-glow" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <g transform={`translate(${cam.x} ${cam.y}) scale(${cam.k})`}>
          <rect x={-2200} y={-1800} width={5800} height={4500} fill="url(#fleet-bg)" />
          <rect x={-2200} y={-1800} width={5800} height={4500} fill="url(#fleet-dots)" />
          {[120, 230, 340, 430].map((radius) => (
            <circle
              key={radius}
              cx={CX}
              cy={CY}
              r={radius}
              fill="none"
              stroke="#1e293b"
              strokeWidth="1"
            />
          ))}
          {graph.sector && (
            <path
              d={graph.sector.d}
              fill={graph.sector.local ? "#34d399" : "#818cf8"}
              opacity="0.08"
            />
          )}
          {graph.edges.map((edge) => {
            const line = edgeEnds(edge.from, edge.to);
            if (!line) return null;
            const target = items.find((item) => item.id === edge.to);
            const live = edge.from === "cloud" && Boolean(target?.online);
            const bound = target?.kind === "agent" ? target.bound : true;
            return (
              <line
                key={`${edge.from}-${edge.to}`}
                x1={line.x1}
                y1={line.y1}
                x2={line.x2}
                y2={line.y2}
                stroke={live ? "#38bdf8" : "#64748b"}
                strokeWidth={edge.from === "cloud" ? 1.6 : 1}
                strokeOpacity={edgeAlpha(edge.from, edge.to)}
                strokeDasharray={bound ? undefined : "3 4"}
                className={live ? "fleet-edge-live" : undefined}
              />
            );
          })}
          {[...items.filter((item) => item.kind === "agent"), ...items.filter((item) => item.kind === "device"), ...items.filter((item) => item.kind === "cloud")].map((item) => {
            const at = graph.pos.get(item.id);
            if (!at) return null;
            const active = item.id === selectedId;
            const alpha = nodeAlpha(item);
            if (item.kind === "cloud") {
              return (
                <g
                  key={item.id}
                  data-node="cloud"
                  opacity={alpha}
                  className="cursor-pointer"
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={() => onSelect(item)}
                  onPointerEnter={(event) => placeTip(item.id, event)}
                  onPointerMove={(event) => placeTip(item.id, event)}
                  onPointerLeave={() => setHover(null)}
                >
                  {item.online && (
                    <circle cx={at.x} cy={at.y} r={58} fill="none" stroke="#38bdf8" strokeOpacity="0.35">
                      <animate attributeName="r" values="52;68;52" dur="3.6s" repeatCount="indefinite" />
                      <animate
                        attributeName="stroke-opacity"
                        values="0.4;0;0.4"
                        dur="3.6s"
                        repeatCount="indefinite"
                      />
                    </circle>
                  )}
                  <circle
                    cx={at.x}
                    cy={at.y}
                    r={at.r}
                    fill="#082f49"
                    stroke={item.online ? "#38bdf8" : "#64748b"}
                    strokeWidth="2"
                    filter="url(#fleet-glow)"
                  />
                  {active && (
                    <circle cx={at.x} cy={at.y} r={at.r + 8} fill="none" stroke="#e2e8f0" strokeWidth="1.5" />
                  )}
                  <text
                    x={at.x}
                    y={at.y + 5}
                    textAnchor="middle"
                    fill="#f8fafc"
                    fontSize="16"
                    fontWeight="650"
                  >
                    {item.label}
                  </text>
                  <text x={at.x + at.r + 12} y={at.y + 4} textAnchor="start" fill="#7dd3fc" fontSize="12">
                    {short(item.detail, 28)}
                  </text>
                </g>
              );
            }
            if (item.kind === "device") {
              const stroke = !item.online ? "#64748b" : item.local ? "#34d399" : "#a5b4fc";
              const fill = item.local ? "#022c22" : "#1e1b4b";
              return (
                <g
                  key={item.id}
                  data-node="device"
                  opacity={alpha}
                  className="cursor-pointer"
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={() => onSelect(item)}
                  onPointerEnter={(event) => placeTip(item.id, event)}
                  onPointerMove={(event) => placeTip(item.id, event)}
                  onPointerLeave={() => setHover(null)}
                >
                  <circle cx={at.x} cy={at.y} r={at.r} fill={fill} stroke={stroke} strokeWidth="2" />
                  {active && (
                    <circle cx={at.x} cy={at.y} r={at.r + 7} fill="none" stroke="#e2e8f0" strokeWidth="1.5" />
                  )}
                  <text
                    x={at.x}
                    y={at.y + 1}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fill="#f8fafc"
                    fontSize="15"
                    fontWeight="650"
                  >
                    {item.agentCount}
                  </text>
                  <text
                    x={at.labelX}
                    y={at.labelY}
                    textAnchor={at.anchor}
                    fill="#e2e8f0"
                    fontSize="13"
                    fontWeight="600"
                  >
                    {short(item.label, 16)}
                  </text>
                  <text
                    x={at.labelX}
                    y={at.labelY + 15}
                    textAnchor={at.anchor}
                    fill="#94a3b8"
                    fontSize="10"
                  >
                    {item.local ? "本机" : "其他端"} · {item.online ? "在线" : "离线"}
                  </text>
                </g>
              );
            }
            const color = agentFill(item);
            const showLabel = Boolean(q) && matches(item, q);
            return (
              <g
                key={item.id}
                data-node="agent"
                opacity={alpha}
                className="cursor-pointer"
                onPointerDown={(event) => event.stopPropagation()}
                onClick={() => onSelect(item)}
                onPointerEnter={(event) => placeTip(item.id, event)}
                onPointerMove={(event) => placeTip(item.id, event)}
                onPointerLeave={() => setHover(null)}
              >
                <circle
                  cx={at.x}
                  cy={at.y}
                  r={active ? at.r + 2.5 : at.r}
                  fill={item.bound ? color : "none"}
                  stroke={color}
                  strokeWidth={item.bound ? 1 : 1.4}
                />
                {showLabel && (
                  <text
                    x={at.labelX}
                    y={at.labelY}
                    textAnchor={at.anchor}
                    fill="#e2e8f0"
                    fontSize="11"
                  >
                    {short(item.label, 14)}
                  </text>
                )}
              </g>
            );
          })}
          {graph.deviceCount === 0 && (
            <text x={CX} y={CY + 92} textAnchor="middle" fill="#64748b" fontSize="14">
              还没有设备。扫描本机，或在其他机器上运行连接器。
            </text>
          )}
        </g>
      </svg>

      {hoverItem && hover && (
        <div
          className="pointer-events-none absolute z-10 max-w-[220px] rounded-lg border border-slate-700 bg-slate-900/95 px-2.5 py-1.5 shadow-lg"
          style={{ left: hover.x, top: hover.y }}
        >
          <p className="truncate text-sm text-slate-100">{hoverItem.label}</p>
          <p className="truncate text-[11px] text-slate-400">
            {hoverItem.kind === "agent" ? `${hoverItem.parentLabel} · ` : ""}
            {hoverItem.detail}
            {hoverItem.kind === "agent" ? ` · ${hoverItem.bound ? "已绑定" : "未绑定"}` : ""}
          </p>
        </div>
      )}

      <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap gap-x-3 gap-y-1 rounded-lg border border-slate-800 bg-slate-950/80 px-2.5 py-1.5 text-[10px] text-slate-400">
        <span className="text-sky-300">云端</span>
        <span className="text-emerald-300">本机</span>
        <span className="text-indigo-300">其他端</span>
        <span>实心已绑定</span>
        <span>空心未绑定</span>
        <span className="text-slate-500">拖拽平移 · 滚轮缩放</span>
      </div>
      <div className="absolute bottom-3 right-3 flex items-center gap-1 rounded-lg border border-slate-800 bg-slate-950/85 p-1">
        <button
          type="button"
          onClick={() => zoomBy(1 / 1.15)}
          className="rounded px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
          aria-label="缩小"
        >
          −
        </button>
        <button
          type="button"
          onClick={() => setCam({ x: 0, y: 0, k: 1 })}
          className="rounded px-2 py-1 text-[11px] text-slate-400 hover:bg-slate-800"
        >
          {Math.round(cam.k * 100)}%
        </button>
        <button
          type="button"
          onClick={() => zoomBy(1.15)}
          className="rounded px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
          aria-label="放大"
        >
          +
        </button>
      </div>
    </div>
  );
}
