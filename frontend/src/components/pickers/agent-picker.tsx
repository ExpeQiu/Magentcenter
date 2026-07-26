"use client";

import { useEffect, useRef, useState } from "react";
import type { AgentInfo, RuntimeName } from "@/lib/types";

export function agentRefKey(a: Pick<AgentInfo, "runtime" | "id">): string {
  return `${a.runtime || "openclaw"}:${a.id}`;
}

export function parseAgentRef(value: string): {
  runtime: RuntimeName;
  agentId: string;
} {
  const idx = value.indexOf(":");
  if (idx <= 0) {
    return { runtime: "openclaw", agentId: value };
  }
  const runtime = value.slice(0, idx) as RuntimeName;
  const agentId = value.slice(idx + 1);
  return { runtime: runtime || "openclaw", agentId };
}

interface AgentPickerProps {
  value: string;
  onChange: (ref: string, agent?: AgentInfo) => void;
  agents?: AgentInfo[];
  placeholder?: string;
}

export function AgentPicker({
  value,
  onChange,
  agents: externalAgents,
  placeholder = "选择 Agent…",
}: AgentPickerProps) {
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState<AgentInfo[]>(externalAgents || []);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (externalAgents) {
      setAgents(externalAgents);
      return;
    }
    import("@/lib/api").then(({ api }) =>
      api.agents().then(setAgents).catch(console.error)
    );
  }, [externalAgents]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const selected = agents.find((a) => agentRefKey(a) === value);
  const filtered = agents.filter(
    (a) =>
      !search ||
      a.id.includes(search) ||
      a.name.includes(search) ||
      a.identity_name.includes(search) ||
      (a.runtime || "").includes(search)
  );

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-left text-sm"
      >
        {selected ? (
          <span>
            <span className="mr-2 rounded bg-slate-700 px-1.5 py-0.5 text-[10px] uppercase text-slate-300">
              {selected.runtime}
            </span>
            {selected.identity_emoji} {selected.name}{" "}
            <span className="text-slate-500">({selected.id})</span>
          </span>
        ) : (
          <span className="text-slate-500">{placeholder}</span>
        )}
        <span className="text-slate-500">▾</span>
      </button>
      {open && (
        <div className="absolute z-50 mt-1 max-h-64 w-full overflow-hidden rounded-lg border border-slate-700 bg-slate-900 shadow-xl">
          <input
            autoFocus
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索 Agent / runtime…"
            className="w-full border-b border-slate-700 bg-slate-900 px-3 py-2 text-sm outline-none"
          />
          <ul className="max-h-48 overflow-y-auto">
            {filtered.map((a) => (
              <li key={agentRefKey(a)}>
                <button
                  type="button"
                  onClick={() => {
                    onChange(agentRefKey(a), a);
                    setOpen(false);
                    setSearch("");
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-slate-800"
                >
                  <span className="w-14 shrink-0 text-[10px] uppercase text-slate-500">
                    {a.runtime}
                  </span>
                  <span>{a.identity_emoji || "🤖"}</span>
                  <span className="flex-1 truncate">{a.name}</span>
                  <span className="text-xs text-slate-500">{a.id}</span>
                </button>
              </li>
            ))}
            {filtered.length === 0 && (
              <li className="px-3 py-4 text-center text-sm text-slate-500">
                无匹配 Agent
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
