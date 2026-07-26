"use client";

import type { SwarmGraph, SwarmNode } from "@/lib/types";

const ROLE_LABEL: Record<string, string> = {
  root: "Root",
  worker: "Worker",
  verifier: "Verifier",
  synthesizer: "Synthesizer",
};

const ROLE_COLOR: Record<string, string> = {
  root: "border-sky-500/60 bg-sky-950/40 text-sky-100",
  worker: "border-indigo-500/50 bg-indigo-950/30 text-indigo-100",
  verifier: "border-amber-500/50 bg-amber-950/30 text-amber-100",
  synthesizer: "border-emerald-500/50 bg-emerald-950/30 text-emerald-100",
};

function NodeCard({ node }: { node: SwarmNode }) {
  const color = ROLE_COLOR[node.role] || "border-slate-700 bg-slate-900 text-slate-200";
  return (
    <div className={`min-w-[140px] max-w-[200px] rounded-lg border px-3 py-2 ${color}`}>
      <p className="text-[10px] uppercase tracking-wide opacity-70">
        {ROLE_LABEL[node.role] || node.role}
      </p>
      <p className="mt-0.5 truncate text-sm font-medium">
        {node.title || node.id}
      </p>
      <p className="mt-1 font-mono text-[10px] opacity-60">{node.id}</p>
      {(node.assignee || node.status) && (
        <p className="mt-1 text-[10px] opacity-70">
          {node.assignee || "—"} · {node.status || "—"}
        </p>
      )}
    </div>
  );
}

export function SwarmGraphView({ graph }: { graph: SwarmGraph }) {
  const byRole = (role: string) => graph.nodes.filter((n) => n.role === role);
  const roots = byRole("root");
  const workers = byRole("worker");
  const verifiers = byRole("verifier");
  const synths = byRole("synthesizer");

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-slate-200">Swarm 拓扑</p>
          <p className="text-xs text-slate-500">
            {graph.goal || "—"} · root {graph.root_id}
          </p>
        </div>
        <p className="text-[10px] text-slate-600">
          workers → verifier → synthesizer
        </p>
      </div>
      <div className="flex flex-col items-center gap-3">
        {roots.length > 0 && (
          <div className="flex flex-wrap justify-center gap-2">
            {roots.map((n) => (
              <NodeCard key={n.id} node={n} />
            ))}
          </div>
        )}
        {workers.length > 0 && (
          <>
            <div className="h-4 w-px bg-slate-700" />
            <div className="flex flex-wrap justify-center gap-2">
              {workers.map((n) => (
                <NodeCard key={n.id} node={n} />
              ))}
            </div>
          </>
        )}
        {verifiers.length > 0 && (
          <>
            <div className="h-4 w-px bg-slate-700" />
            <div className="flex flex-wrap justify-center gap-2">
              {verifiers.map((n) => (
                <NodeCard key={n.id} node={n} />
              ))}
            </div>
          </>
        )}
        {synths.length > 0 && (
          <>
            <div className="h-4 w-px bg-slate-700" />
            <div className="flex flex-wrap justify-center gap-2">
              {synths.map((n) => (
                <NodeCard key={n.id} node={n} />
              ))}
            </div>
          </>
        )}
      </div>
      {graph.edges.length > 0 && (
        <p className="mt-3 text-center text-[10px] text-slate-600">
          {graph.edges.length} 条依赖边
        </p>
      )}
    </div>
  );
}
