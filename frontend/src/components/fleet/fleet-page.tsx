"use client";

import { useEffect, useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/context/workspace-context";
import { normalizeNode, useTerminal } from "@/lib/context/terminal-context";
import type { FleetNode, FleetScan } from "@/lib/types";

function agentKey(agent: { runtime: string; id: string }) {
  return `${agent.runtime}:${agent.id}`;
}

function modeLabel(mode: FleetNode["mode"]) {
  if (mode === "local") return "本机";
  if (mode === "webhook") return "webhook";
  return "连接器";
}

export function FleetPage() {
  const { workspaceId, workspace } = useWorkspace();
  const { nodes, selected, error, select, refresh } = useTerminal();
  const [scan, setScan] = useState<FleetScan | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState("");
  const [localPicked, setLocalPicked] = useState<string[]>([]);
  const [deviceName, setDeviceName] = useState("");
  const [picked, setPicked] = useState<Record<string, string[]>>({});
  const [msg, setMsg] = useState("");

  useEffect(() => {
    setPicked((prev) => {
      const next = { ...prev };
      for (const node of nodes) {
        if (!next[node.id]) {
          const source = node.bound ? node.agents : node.seen;
          next[node.id] = source.map(agentKey);
        }
      }
      return next;
    });
  }, [nodes]);

  const runScan = async () => {
    setScanning(true);
    setScanError("");
    setMsg("");
    try {
      const result = await api.fleetScan();
      setScan(result);
      setDeviceName(result.name);
      const local = nodes.find((n) => n.id === result.node_id && n.bound);
      const boundKeys = new Set((local?.agents || []).map(agentKey));
      setLocalPicked(
        result.agents.filter((a) => boundKeys.size === 0 || boundKeys.has(agentKey(a))).map(agentKey)
      );
      console.info("fleet scan", result.node_id, result.agents.length);
    } catch (err) {
      console.error(err);
      setScanError(err instanceof Error ? err.message : "扫描失败");
    } finally {
      setScanning(false);
    }
  };

  const bindLocal = async () => {
    if (!scan) return;
    const agents = scan.agents.filter((a) => localPicked.includes(agentKey(a)));
    setMsg("");
    try {
      const node = normalizeNode(
        await api.fleetBind({
          node_id: scan.node_id,
          name: deviceName.trim() || scan.name,
          workspace_id: workspaceId,
          agents,
        })
      );
      setMsg(`已绑定 ${node.name} · ${node.agents.length} 个智能体`);
      setPicked((prev) => ({ ...prev, [node.id]: node.agents.map(agentKey) }));
      select(node.id);
      refresh();
    } catch (err) {
      console.error(err);
      setMsg(err instanceof Error ? err.message : "绑定失败");
    }
  };

  const bindNode = async (node: FleetNode) => {
    const pool = node.seen.length ? node.seen : node.agents;
    const keys = new Set(picked[node.id] || []);
    const agents = pool.filter((a) => keys.has(agentKey(a)));
    setMsg("");
    try {
      const saved = normalizeNode(
        await api.fleetBind({
          node_id: node.id,
          name: node.name,
          workspace_id: workspaceId,
          agents,
        })
      );
      setMsg(`已绑定 ${saved.name} · ${saved.agents.length} 个智能体`);
      setPicked((prev) => ({ ...prev, [node.id]: saved.agents.map(agentKey) }));
      select(saved.id);
      refresh();
    } catch (err) {
      console.error(err);
      setMsg(err instanceof Error ? err.message : "绑定失败");
    }
  };

  const unbind = async (node: FleetNode) => {
    setMsg("");
    try {
      await api.fleetUnbind(node.id);
      setMsg(`已解除 ${node.name}`);
      setPicked((prev) => {
        const next = { ...prev };
        delete next[node.id];
        return next;
      });
      refresh();
    } catch (err) {
      console.error(err);
      setMsg(err instanceof Error ? err.message : "解除失败");
    }
  };

  const toggle = (list: string[], key: string, on: boolean) =>
    on ? Array.from(new Set([...list, key])) : list.filter((item) => item !== key);

  return (
    <div>
      <PageHeader
        title="多端"
        description={`${workspace?.name || "当前团队"} · ${selected?.name || "未选择终端"}。左上角按设备名切换。给智能体分配任务请到「任务」。`}
      />
      {error && <p className="mb-4 text-sm text-rose-300">{error}</p>}
      {msg && <p className="mb-4 text-sm text-slate-300">{msg}</p>}

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium">本机扫描</p>
            <p className="mt-1 text-xs text-slate-500">
              发现这台协调器上的 OpenClaw / Hermes，勾选后绑定。
            </p>
          </div>
          <button
            type="button"
            onClick={runScan}
            disabled={scanning}
            className="rounded-lg bg-sky-500 px-3 py-1.5 text-sm font-medium text-slate-950 disabled:opacity-50"
          >
            {scanning ? "扫描中" : "扫描本机"}
          </button>
        </div>
        {scanError && <p className="mt-3 text-sm text-rose-300">{scanError}</p>}
        {scan && (
          <div className="mt-4 space-y-3">
            <p className="text-xs text-slate-400">
              {scan.hostname} · {scan.agents.length} 个智能体
            </p>
            {nodes.some((n) => n.id === scan.node_id && n.mode !== "local") && (
              <p className="text-xs text-amber-200">
                这台机器已由连接器上报。绑定使用它上报的智能体，也可以在下方设备卡片里操作。
              </p>
            )}
            {scan.agents.length === 0 ? (
              <p className="text-sm text-slate-500">没有发现可绑定的智能体。</p>
            ) : (
              <ul className="space-y-2">
                {scan.agents.map((agent) => {
                  const key = agentKey(agent);
                  return (
                    <li key={key}>
                      <label className="flex items-center gap-3 text-sm">
                        <input
                          type="checkbox"
                          checked={localPicked.includes(key)}
                          onChange={(e) =>
                            setLocalPicked((cur) => toggle(cur, key, e.target.checked))
                          }
                        />
                        <span className="text-slate-200">{agent.name}</span>
                        <span className="text-xs text-slate-500">
                          {agent.runtime}
                          {agent.model ? ` · ${agent.model}` : ""}
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
            <div className="flex flex-wrap items-end gap-3">
              <label className="text-xs text-slate-400">
                设备名称
                <input
                  value={deviceName}
                  onChange={(e) => setDeviceName(e.target.value)}
                  className="mt-1 block rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
                />
              </label>
              <button
                type="button"
                onClick={bindLocal}
                disabled={!localPicked.length}
                className="rounded-lg bg-sky-500 px-3 py-1.5 text-sm font-medium text-slate-950 disabled:opacity-50"
              >
                绑定
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="mt-6">
        <p className="mb-3 text-sm font-medium">设备</p>
        {!selected ? (
          <p className="text-sm text-slate-500">还没有设备。扫描本机，或在其他机器上运行连接器。</p>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {[selected].map((node) => {
              const pool = node.seen.length ? node.seen : node.agents;
              const keys = picked[node.id] || [];
              return (
                <article
                  key={node.id}
                  className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-base font-semibold text-slate-100">{node.name}</p>
                      <p className="mt-1 text-xs text-slate-500">
                        {node.hostname || node.id} · {modeLabel(node.mode)}
                      </p>
                    </div>
                    <div className="text-right text-xs">
                      <p className={node.online ? "text-emerald-300" : "text-slate-500"}>
                        {node.online ? "在线" : "离线"}
                      </p>
                      <p className={node.bound ? "text-sky-300" : "text-amber-200"}>
                        {node.bound ? "已绑定" : "待绑定"}
                      </p>
                    </div>
                  </div>
                  {pool.length === 0 ? (
                    <p className="mt-3 text-sm text-slate-500">还没有扫描到智能体。</p>
                  ) : (
                    <ul className="mt-3 space-y-2">
                      {pool.map((agent) => {
                        const key = agentKey(agent);
                        return (
                          <li key={key}>
                            <label className="flex items-center gap-3 text-sm">
                              <input
                                type="checkbox"
                                checked={keys.includes(key)}
                                onChange={(e) =>
                                  setPicked((prev) => ({
                                    ...prev,
                                    [node.id]: toggle(keys, key, e.target.checked),
                                  }))
                                }
                              />
                              <span className="text-slate-200">{agent.name}</span>
                              <span className="text-xs text-slate-500">{agent.runtime}</span>
                            </label>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => bindNode(node)}
                      disabled={!keys.length}
                      className="rounded-lg bg-sky-500 px-3 py-1.5 text-sm font-medium text-slate-950 disabled:opacity-50"
                    >
                      {node.bound ? "更新绑定" : "绑定"}
                    </button>
                    {node.bound && (
                      <button
                        type="button"
                        onClick={() => unbind(node)}
                        className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300"
                      >
                        解除绑定
                      </button>
                    )}
                    {(node.queued_count > 0 || node.running_count > 0) && (
                      <span className="self-center text-xs text-slate-500">
                        排队 {node.queued_count} · 执行 {node.running_count}
                      </span>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
