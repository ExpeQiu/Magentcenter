"use client";

import { useEffect, useRef, useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/context/workspace-context";
import { normalizeNode, useTerminal } from "@/lib/context/terminal-context";
import type { FleetLink, FleetNode, FleetScan } from "@/lib/types";

const CAP_LABEL: Record<string, string> = {
  "openclaw.agent": "OpenClaw",
  "hermes.chat": "Hermes",
  "task.execute": "可执行任务",
};

function capLabel(cap: string) {
  return CAP_LABEL[cap] || cap;
}

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
  const [link, setLink] = useState<FleetLink | null>(null);
  const [cloudUrl, setCloudUrl] = useState("");
  const [linking, setLinking] = useState(false);
  const [linkError, setLinkError] = useState("");
  const cloudTouched = useRef(false);

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

  useEffect(() => {
    let cancelled = false;
    const pull = () => {
      api
        .fleetLink(workspaceId)
        .then((data) => {
          if (cancelled) return;
          setLink(data);
          if (!cloudTouched.current) setCloudUrl(data.cloud_url || "");
          console.info(
            "fleet link state=%s node=%s peers=%d",
            data.state || "-",
            data.node_id || "-",
            data.peers.length
          );
        })
        .catch((err) => {
          console.error(err);
          if (!cancelled) setLinkError(err instanceof Error ? err.message : "读不到云端链接");
        });
    };
    pull();
    const timer = window.setInterval(pull, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [workspaceId]);

  const openLink = async () => {
    setLinking(true);
    setLinkError("");
    setMsg("");
    try {
      const saved = await api.fleetOpenLink({
        cloud_url: cloudUrl.trim(),
        workspace_id: workspaceId,
      });
      setLink(saved);
      setCloudUrl(saved.cloud_url || "");
      setMsg(
        `已绑定本机 ${saved.agents.length} 个智能体，云端还有 ${saved.peers.length} 个其他端`
      );
      console.info(
        "fleet handshake ok node=%s agents=%d peers=%d",
        saved.node_id,
        saved.agents.length,
        saved.peers.length
      );
      refresh();
    } catch (err) {
      console.error(err);
      setLinkError(err instanceof Error ? err.message : "握手失败");
    } finally {
      setLinking(false);
    }
  };

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
        description={`${workspace?.name || "当前团队"} · ${selected?.name || "未选择终端"}。把本机资源绑定到云端后，可以看见其他端的智能体和能力。分配任务仍在「任务」。`}
      />
      {error && <p className="mb-4 text-sm text-rose-300">{error}</p>}
      {msg && <p className="mb-4 text-sm text-slate-300">{msg}</p>}

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium">绑定到云端</p>
            <p className="mt-1 text-xs text-slate-500">
              握手后把本机扫到的智能体交给云端，并取回其他端已经绑定的资源与能力。地址留空表示这台协调器。
            </p>
          </div>
          <button
            type="button"
            onClick={openLink}
            disabled={linking}
            className="rounded-lg bg-sky-500 px-3 py-1.5 text-sm font-medium text-slate-950 disabled:opacity-50"
          >
            {linking ? "握手中" : "握手并绑定"}
          </button>
        </div>
        <label className="mt-3 block text-xs text-slate-400">
          云端地址
          <input
            value={cloudUrl}
            onChange={(e) => {
              cloudTouched.current = true;
              setCloudUrl(e.target.value);
            }}
            placeholder="http://云端:8013"
            className="mt-1 block w-full max-w-md rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
          />
        </label>
        {link && !link.enroll_configured && (
          <p className="mt-3 text-xs text-slate-500">
            未配置注册令牌时，只能绑定到本机协调器。连接其他云端或让其他机器接入，需要先设置注册令牌。
          </p>
        )}
        {linkError && <p className="mt-3 text-sm text-rose-300">{linkError}</p>}
        {link?.state === "failed" && link.detail && (
          <p className="mt-3 text-sm text-rose-300">{link.detail}</p>
        )}
        {link?.state === "ok" && (
          <div className="mt-4 space-y-3">
            <p className="text-xs text-slate-400">
              本机已绑定 {link.agents.length} 个智能体
              {link.capabilities.length
                ? ` · ${link.capabilities.map(capLabel).join(" · ")}`
                : ""}
              {link.local_cloud ? " · 本机协调器" : ` · ${link.cloud_url}`}
            </p>
            <div>
              <p className="text-sm font-medium">其他端</p>
              {link.peers.length === 0 ? (
                <p className="mt-2 text-sm text-slate-500">云端还没有其他端的资源。</p>
              ) : (
                <div className="mt-2 grid gap-3 lg:grid-cols-2">
                  {link.peers.map((peer) => (
                    <article
                      key={peer.id}
                      className="rounded-2xl border border-slate-800 bg-slate-950/40 p-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-slate-100">{peer.name}</p>
                          <p className="mt-1 text-xs text-slate-500">
                            {peer.hostname || peer.id}
                          </p>
                        </div>
                        <p className={peer.online ? "text-xs text-emerald-300" : "text-xs text-slate-500"}>
                          {peer.online ? "在线" : "离线"}
                        </p>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {(peer.capabilities.length ? peer.capabilities : peer.runtimes).map((cap) => (
                          <span
                            key={cap}
                            className="rounded-full border border-slate-700 px-2 py-0.5 text-xs text-slate-300"
                          >
                            {capLabel(cap)}
                          </span>
                        ))}
                      </div>
                      {peer.agents.length === 0 ? (
                        <p className="mt-2 text-sm text-slate-500">没有绑定智能体。</p>
                      ) : (
                        <ul className="mt-2 space-y-1">
                          {peer.agents.map((agent) => (
                            <li key={agentKey(agent)} className="text-sm text-slate-300">
                              {agent.name}
                              <span className="ml-2 text-xs text-slate-500">{agent.runtime}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </article>
                  ))}
                </div>
              )}
              <p className="mt-2 text-xs text-slate-500">
                {link.local_cloud
                  ? "这些终端已在本协调器上，左上角切换后可以在「任务」里分配。"
                  : "这些资源在云端。要分配任务，请到云端控制台。"}
              </p>
            </div>
          </div>
        )}
      </section>

      <section className="mt-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
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
                        {node.handshake === "ok" ? " · 已握手" : ""}
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
