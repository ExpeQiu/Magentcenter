"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AgentInfo } from "@/lib/types";

interface ProjectLeadPickerProps {
  leadType: string;
  leadId: string;
  onChange: (leadType: string, leadId: string) => void;
}

export function ProjectLeadPicker({
  leadType,
  leadId,
  onChange,
}: ProjectLeadPickerProps) {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.agents().then(setAgents).catch(console.error);
  }, []);

  const current = agents.find((a) => a.id === leadId);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
      >
        {current ? (
          <>
            <span>{current.identity_emoji || "🤖"}</span>
            <span>{current.name}</span>
          </>
        ) : (
          <span className="text-slate-500">选择 Lead Agent…</span>
        )}
      </button>
      {open && (
        <div className="absolute left-0 top-full z-20 mt-1 max-h-48 w-56 overflow-y-auto rounded-lg border border-slate-700 bg-slate-900 py-1 shadow-xl">
          <button
            className="block w-full px-3 py-2 text-left text-sm text-slate-400 hover:bg-slate-800"
            onClick={() => {
              onChange("", "");
              setOpen(false);
            }}
          >
            清除 Lead
          </button>
          {agents.map((a) => (
            <button
              key={a.id}
              className="block w-full px-3 py-2 text-left text-sm hover:bg-slate-800"
              onClick={() => {
                onChange("agent", a.id);
                setOpen(false);
              }}
            >
              {a.identity_emoji || "🤖"} {a.name}
              <span className="ml-2 text-xs text-slate-500">{a.id}</span>
            </button>
          ))}
        </div>
      )}
      {leadType && leadId && (
        <p className="mt-1 text-xs text-slate-500">
          Lead: {leadType} / {leadId}
        </p>
      )}
    </div>
  );
}
