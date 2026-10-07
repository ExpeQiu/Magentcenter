"use client";

import { useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { FleetGraph, buildFleetGraph, type FleetGraphItem } from "@/components/fleet/fleet-graph";
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
  const [graphId, setGraphId] = useState("cloud");
  const [query, setQuery] = useState("");
  const cloudTouched = useRef(false);
  const graphLog = useRef("");

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
      setGraphId(result.node_id);
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

  const items = useMemo(
    () =>
      buildFleetGraph({
        link,
        nodes,
        scan,
        localPicked,
        picked,
        preferId: selected?.id,
      }),
    [link, nodes, scan, localPicked, picked, selected?.id]
  );

  useEffect(() => {
    const devices = items.filter((item) => item.kind === "device");
    const sig = devices.map((item) => `${item.id}:${item.agentCount}`).join(",");
    if (sig === graphLog.current) return;
    graphLog.current = sig;
    console.info(
      "fleet graph devices=%d agents=%d",
      devices.length,
      items.filter((item) => item.kind === "agent").length
    );
  }, [items]);

  const active = items.find((item) => item.id === graphId) || items[0];

  const choose = (item: FleetGraphItem) => {
    setGraphId(item.id);
    if (item.kind === "device" && nodes.some((node) => node.id === item.id)) select(item.id);
    console.info("fleet graph select id=%s kind=%s label=%s", item.id, item.kind, item.label);
  };

  const q = query.trim().toLowerCase();
  const matchCount = q
    ? items.filter((item) => item.kind === "agent" && `${item.label} ${item.runtime} ${item.model}`.toLowerCase().includes(q)).length
    : 0;

  return (
    <div>
      <PageHeader
        title="多端"
        description={`${workspace?.name || "当前团队"} · ${selected?.name || "未选择终端"}。云端在中心，设备和智能体按绑定关系展开。分配任务仍在「任务」。`}
      />
      {error && <p className="mb-3 text-sm text-rose-300">{error}</p>}
      {msg && <p className="mb-3 text-sm text-slate-300">{msg}</p>}

      <div className="mb-3 flex flex-wrap items-end gap-3">
        <label className="min-w-[16rem] flex-1 text-xs text-slate-400">
          云端地址
          <input
            value={cloudUrl}
            onChange={(e) => {
              cloudTouched.current = true;
              setCloudUrl(e.target.value);
            }}
            placeholder="http://云端:8013"
            className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
          />
        </label>
        <button
          type="button"
          onClick={openLink}
          disabled={linking}
          className="rounded-lg bg-sky-500 px-3 py-1.5 text-sm font-medium text-slate-950 disabled:opacity-50"
        >
          {linking ? "握手中" : "握手并绑定"}
        </button>
        <button
          type="button"
          onClick={runScan}
          disabled={scanning}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200 disabled:opacity-50"
        >
          {scanning ? "扫描中" : "扫描本机"}
        </button>
        <label className="min-w-[12rem] text-xs text-slate-400">
          搜索智能体
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="名称或运行时"
            className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
          />
        </label>
      </div>
      {q && (
        <p className="mb-3 text-xs text-slate-500">
          {matchCount ? `图谱中 ${matchCount} 个智能体匹配` : "没有匹配的智能体"}
        </p>
      )}
      {link && !link.enroll_configured && (
        <p className="mb-3 text-xs text-slate-500">
          未配置注册令牌时，只能绑定到本机协调器。连接其他云端或让其他机器接入，需要先设置注册令牌。
        </p>
      )}
      {linkError && <p className="mb-3 text-sm text-rose-300">{linkError}</p>}
      {scanError && <p className="mb-3 text-sm text-rose-300">{scanError}</p>}
      {link?.state === "failed" && link.detail && (
        <p className="mb-3 text-sm text-rose-300">{link.detail}</p>
      )}

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_20.5rem]">
        <FleetGraph items={items} selectedId={active?.id || "cloud"} query={query} onSelect={choose} />
        <FleetInspector
          item={active}
          items={items}
          nodes={nodes}
          scan={scan}
          link={link}
          deviceName={deviceName}
          setDeviceName={setDeviceName}
          localPicked={localPicked}
          setLocalPicked={setLocalPicked}
          picked={picked}
          setPicked={setPicked}
          scanning={scanning}
          onScan={runScan}
          onBindLocal={bindLocal}
          onBindNode={bindNode}
          onUnbind={unbind}
          onOpen={choose}
          toggle={toggle}
        />
      </div>
    </div>
  );
}

function capChips(caps: string[]) {
  if (!caps.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {caps.map((cap) => (
        <span key={cap} className="rounded-full border border-slate-700 px-2 py-0.5 text-xs text-slate-300">
          {capLabel(cap)}
        </span>
      ))}
    </div>
  );
}

function FleetInspector({
  item,
  items,
  nodes,
  scan,
  link,
  deviceName,
  setDeviceName,
  localPicked,
  setLocalPicked,
  picked,
  setPicked,
  scanning,
  onScan,
  onBindLocal,
  onBindNode,
  onUnbind,
  onOpen,
  toggle,
}: {
  item: FleetGraphItem | undefined;
  items: FleetGraphItem[];
  nodes: FleetNode[];
  scan: FleetScan | null;
  link: FleetLink | null;
  deviceName: string;
  setDeviceName: (value: string) => void;
  localPicked: string[];
  setLocalPicked: Dispatch<SetStateAction<string[]>>;
  picked: Record<string, string[]>;
  setPicked: Dispatch<SetStateAction<Record<string, string[]>>>;
  scanning: boolean;
  onScan: () => void;
  onBindLocal: () => void;
  onBindNode: (node: FleetNode) => void;
  onUnbind: (node: FleetNode) => void;
  onOpen: (item: FleetGraphItem) => void;
  toggle: (list: string[], key: string, on: boolean) => string[];
}) {
  const shell = "h-[calc(100svh-14rem)] min-h-[540px] overflow-y-auto rounded-2xl border border-slate-800 bg-slate-900/40 p-4";
  if (!item || item.kind === "cloud") {
    const devices = items.filter((entry) => entry.kind === "device");
    return (
      <aside className={shell}>
        <p className="text-sm font-medium text-slate-100">{item?.label || "云端"}</p>
        <p className="mt-1 text-xs text-slate-500">{item?.detail || "未连接"}</p>
        <p className="mt-3 text-sm text-slate-300">
          {link?.state === "ok" ? "已握手" : link?.state === "failed" ? "握手失败" : "未握手"}
          {typeof item?.agentCount === "number" ? ` · ${item.agentCount} 个智能体` : ""}
          {link?.local_cloud ? " · 本机协调器" : ""}
        </p>
        {item && capChips(item.capabilities)}
        <p className="mt-4 text-xs text-slate-500">
          {link?.local_cloud
            ? "点开设备可查看智能体。本协调器上的终端可在「任务」里分配。"
            : "点开设备查看智能体。其他端的任务请到云端控制台分配。"}
        </p>
        <ul className="mt-3 space-y-2">
          {devices.length === 0 && <li className="text-sm text-slate-500">还没有设备。</li>}
          {devices.map((device) => (
            <li key={device.id}>
              <button
                type="button"
                onClick={() => onOpen(device)}
                className="flex w-full items-center justify-between gap-3 rounded-xl border border-slate-800 px-3 py-2 text-left hover:border-slate-600"
              >
                <span>
                  <span className="block text-sm text-slate-100">{device.label}</span>
                  <span className="text-[11px] text-slate-500">
                    {device.local ? "本机" : "其他端"} · {device.agentCount} 个智能体
                  </span>
                </span>
                <span className={device.online ? "text-xs text-emerald-300" : "text-xs text-slate-500"}>
                  {device.online ? "在线" : "离线"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
    );
  }

  if (item.kind === "agent") {
    const parent = items.find((entry) => entry.id === item.parentId);
    const node = nodes.find((entry) => entry.id === item.parentId);
    const usingScan = Boolean(scan && node && scan.node_id === node.id);
    const checked = usingScan
      ? localPicked.includes(item.agentKey)
      : (picked[item.parentId] || []).includes(item.agentKey);
    return (
      <aside className={shell}>
        <p className="text-[11px] text-slate-500">{item.local ? "本机智能体" : "其他端智能体"}</p>
        <p className="mt-1 text-base font-semibold text-slate-100">{item.label}</p>
        <p className="mt-1 text-xs text-slate-500">{item.detail}</p>
        <p className="mt-3 text-sm text-slate-300">{item.bound ? "已绑定" : "未绑定"}</p>
        {parent && (
          <button
            type="button"
            onClick={() => onOpen(parent)}
            className="mt-4 text-sm text-sky-300"
          >
            {parent.label}
          </button>
        )}
        {node && (
          <label className="mt-4 flex items-center gap-3 text-sm text-slate-200">
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => {
                if (usingScan) {
                  setLocalPicked((cur) => toggle(cur, item.agentKey, e.target.checked));
                  return;
                }
                setPicked((prev) => ({
                  ...prev,
                  [node.id]: toggle(prev[node.id] || [], item.agentKey, e.target.checked),
                }));
              }}
            />
            加入绑定
          </label>
        )}
      </aside>
    );
  }

  const node = nodes.find((entry) => entry.id === item.id);
  const agents = items.filter((entry) => entry.kind === "agent" && entry.parentId === item.id);
  const usingScan = Boolean(scan && node && scan.node_id === node.id);
  const keys = node ? (usingScan ? localPicked : picked[node.id] || []) : [];

  return (
    <aside className="flex h-[calc(100svh-14rem)] min-h-[540px] flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/40">
      <div className="shrink-0 px-4 pt-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-base font-semibold text-slate-100">{item.label}</p>
            <p className="mt-1 text-xs text-slate-500">
              {item.hostname || item.detail} · {item.local ? "本机" : "其他端"}
            </p>
          </div>
          <div className="text-right text-xs">
            <p className={item.online ? "text-emerald-300" : "text-slate-500"}>
              {item.online ? "在线" : "离线"}
            </p>
            <p className={item.bound ? "text-sky-300" : "text-amber-200"}>
              {item.bound ? "已绑定" : "待绑定"}
              {node?.handshake === "ok" ? " · 已握手" : ""}
            </p>
          </div>
        </div>
        {capChips(item.capabilities)}
        {node && (node.queued_count > 0 || node.running_count > 0) && (
          <p className="mt-2 text-xs text-slate-500">
            排队 {node.queued_count} · 执行 {node.running_count}
          </p>
        )}
        {!node && (
          <p className="mt-3 text-xs text-slate-500">
            {link?.local_cloud
              ? "这台终端已在本协调器上，可在「任务」里分配。"
              : "这些资源在云端。要分配任务，请到云端控制台。"}
          </p>
        )}
        <p className="mb-2 mt-4 text-sm font-medium text-slate-200">智能体 · {agents.length}</p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-3">
      {node && (
        <p className="mb-2 text-xs text-slate-500">勾选后绑定。图谱里实心点是已选，空心点是未选。</p>
      )}
      {agents.length === 0 ? (
        <p className="text-sm text-slate-500">还没有智能体。</p>
      ) : (
        <ul className="space-y-1.5">
          {agents.map((agent) => (
            <li key={agent.id} className="flex items-center gap-3 text-sm">
              {node && (
                <input
                  type="checkbox"
                  checked={keys.includes(agent.agentKey)}
                  aria-label={`绑定 ${agent.label}`}
                  onChange={(e) => {
                    if (usingScan) {
                      setLocalPicked((cur) => toggle(cur, agent.agentKey, e.target.checked));
                      return;
                    }
                    setPicked((prev) => ({
                      ...prev,
                      [node.id]: toggle(keys, agent.agentKey, e.target.checked),
                    }));
                  }}
                />
              )}
              <button
                type="button"
                onClick={() => onOpen(agent)}
                className="flex min-w-0 flex-1 items-center justify-between gap-3 text-left"
              >
                <span className="truncate text-slate-200">{agent.label}</span>
                <span className="shrink-0 text-xs text-slate-500">{agent.runtime}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      </div>
      {node && (
        <div className="shrink-0 space-y-3 border-t border-slate-800 p-4">
          {usingScan && (
            <label className="block text-xs text-slate-400">
              设备名称
              <input
                value={deviceName}
                onChange={(e) => setDeviceName(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
              />
            </label>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onScan}
              disabled={scanning}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 disabled:opacity-50"
            >
              {scanning ? "扫描中" : "扫描本机"}
            </button>
            <button
              type="button"
              onClick={() => (usingScan ? onBindLocal() : onBindNode(node))}
              disabled={!keys.length}
              className="rounded-lg bg-sky-500 px-3 py-1.5 text-sm font-medium text-slate-950 disabled:opacity-50"
            >
              {usingScan ? "绑定" : node.bound ? "更新绑定" : "绑定"}
            </button>
            {node.bound && (
              <button
                type="button"
                onClick={() => onUnbind(node)}
                className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300"
              >
                解除绑定
              </button>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}

