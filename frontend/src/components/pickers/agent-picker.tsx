"use client";

import { useEffect, useRef, useState } from "react";
import type { AgentInfo } from "@/lib/types";

interface AgentPickerProps {
  value: string;
  onChange: (id: string) => void;
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

  const selected = agents.find((a) => a.id === value);
  const filtered = agents.filter(
    (a) =>
      !search ||
      a.id.includes(search) ||
      a.name.includes(search) ||
      a.identity_name.includes(search)
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
            placeholder="搜索 Agent…"
            className="w-full border-b border-slate-700 bg-slate-900 px-3 py-2 text-sm outline-none"
          />
          <ul className="max-h-48 overflow-y-auto">
            {filtered.map((a) => (
              <li key={a.id}>
                <button
                  type="button"
                  onClick={() => {
                    onChange(a.id);
                    setOpen(false);
                    setSearch("");
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-slate-800"
                >
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
