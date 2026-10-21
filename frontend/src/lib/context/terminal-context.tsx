"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/context/workspace-context";
import {
  defaultEndpointMode,
  isEndpointMode,
  modeOfNode,
  preferredDeviceId,
  reconcileEndpoint,
  restoreEndpoint,
  type EndpointMode,
} from "@/lib/endpoint-mode";
import type { FleetLink, FleetNode, FleetPeer } from "@/lib/types";

function asAgents(value: FleetNode["agents"] | undefined | null) {
  return Array.isArray(value) ? value : [];
}

function asMode(mode: string | undefined): FleetNode["mode"] {
  if (mode === "local" || mode === "webhook" || mode === "plugin" || mode === "voice") return mode;
  return "plugin";
}

function blankNode(partial: FleetNode): FleetNode {
  return normalizeNode(partial);
}

/** 图上的本机和其他端来自云端链接，不一定在本机名册里。 */
export function devicesFromLink(link: FleetLink | null, workspaceId: string): FleetNode[] {
  if (!link || link.state !== "ok") return [];
  const out: FleetNode[] = [];
  if (link.node_id) {
    out.push(
      blankNode({
        id: link.node_id,
        name: "本机",
        runtimes: [],
        agents: link.agents || [],
        seen: link.agents || [],
        hostname: "",
        platform: "",
        mode: "local",
        webhook_url: "",
        online: true,
        enrolled: true,
        bound: Boolean(link.bound),
        workspace_id: workspaceId,
        last_seen: null,
        load: null,
        running_count: 0,
        queued_count: 0,
        capabilities: link.capabilities || [],
        handshake: "ok",
      })
    );
  }
  for (const peer of link.peers || []) {
    if (!peer.id) continue;
    out.push(peerToNode(peer, workspaceId));
  }
  return out;
}

function peerToNode(peer: FleetPeer, workspaceId: string): FleetNode {
  return blankNode({
    id: peer.id,
    name: peer.name || peer.hostname || peer.id,
    runtimes: peer.runtimes || [],
    agents: peer.agents || [],
    seen: peer.agents || [],
    hostname: peer.hostname || "",
    platform: peer.platform || "",
    mode: asMode(peer.mode),
    webhook_url: "",
    online: Boolean(peer.online),
    enrolled: true,
    bound: true,
    workspace_id: workspaceId,
    last_seen: null,
    load: null,
    running_count: 0,
    queued_count: 0,
    capabilities: peer.capabilities || [],
    handshake: "ok",
  });
}

export function mergeTerminals(listed: FleetNode[], extras: FleetNode[]): FleetNode[] {
  const byId = new Map<string, FleetNode>();
  for (const node of listed) byId.set(node.id, node);
  for (const node of extras) {
    if (!byId.has(node.id)) byId.set(node.id, node);
  }
  return [...byId.values()].sort((a, b) => {
    const aLocal = a.mode === "local" ? 0 : 1;
    const bLocal = b.mode === "local" ? 0 : 1;
    if (aLocal !== bLocal) return aLocal - bLocal;
    return a.name.localeCompare(b.name, "zh");
  });
}

export function normalizeNode(node: FleetNode): FleetNode {
  const agents = asAgents(node.agents);
  const seen = asAgents(node.seen);
  if (!Array.isArray(node.agents) || !Array.isArray(node.seen)) {
    console.warn("fleet node missing agent lists", node.id);
  }
  return {
    ...node,
    agents,
    seen,
    runtimes: Array.isArray(node.runtimes) ? node.runtimes : [],
    bound: Boolean(node.bound),
    queued_count: node.queued_count ?? 0,
    running_count: node.running_count ?? 0,
    capabilities: Array.isArray(node.capabilities) ? node.capabilities : [],
    handshake: node.handshake || "",
  };
}

interface TerminalContextValue {
  nodes: FleetNode[];
  selectedId: string;
  selected: FleetNode | null;
  mode: EndpointMode;
  ready: boolean;
  error: string;
  select: (id: string) => void;
  selectMode: (mode: EndpointMode) => void;
  refresh: () => void;
}

const TerminalContext = createContext<TerminalContextValue | null>(null);

export function TerminalProvider({ children }: { children: ReactNode }) {
  const { workspaceId, slug } = useWorkspace();
  const scope = workspaceId || slug;
  const storageKey = `agentcenter.terminal.${scope}`;
  const modeKey = `agentcenter.endpointMode.${scope}`;
  const pickedKey = `agentcenter.endpointPicked.${scope}`;
  const [nodes, setNodes] = useState<FleetNode[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [mode, setMode] = useState<EndpointMode>("pc");
  const [fallback, setFallback] = useState<EndpointMode>("pc");
  const [readyKey, setReadyKey] = useState("");
  const [rosterReady, setRosterReady] = useState(false);
  const [profileReady, setProfileReady] = useState(false);
  const [error, setError] = useState("");
  const restored = useRef(false);

  const refresh = useCallback(() => {
    Promise.all([
      api.fleetNodes(workspaceId).catch((err) => {
        console.error(err);
        return null;
      }),
      api.fleetLink(workspaceId).catch((err) => {
        console.error(err);
        return null;
      }),
    ]).then(([list, link]) => {
      if (!list && !link) {
        setError("无法连接协调器");
        return;
      }
      const merged = mergeTerminals(
        (list || []).map(normalizeNode),
        devicesFromLink(link, workspaceId)
      );
      setNodes(merged);
      setRosterReady(true);
      setError("");
      console.info(
        "terminal roster listed=%d merged=%d link=%s peers=%d",
        list?.length ?? 0,
        merged.length,
        link?.state || "-",
        link?.peers?.length ?? 0
      );
    });
  }, [workspaceId]);

  useEffect(() => {
    restored.current = false;
    setRosterReady(false);
    setProfileReady(false);
  }, [scope]);

  useLayoutEffect(() => {
    const storedMode = window.sessionStorage.getItem(modeKey) || "";
    const picked = window.sessionStorage.getItem(pickedKey) === "1";
    const nextFallback = defaultEndpointMode({ port: window.location.port });
    setSelectedId(window.sessionStorage.getItem(storageKey) || "");
    setFallback(nextFallback);
    setMode(picked && isEndpointMode(storedMode) ? storedMode : nextFallback);
    setReadyKey(storageKey);
    if (nextFallback === "cloud") setProfileReady(true);
    console.info("endpoint fallback=%s port=%s picked=%s", nextFallback, window.location.port || "-", picked);
  }, [storageKey, modeKey, pickedKey]);

  useEffect(() => {
    let cancelled = false;
    api
      .health()
      .then((health) => {
        if (cancelled) return;
        const next = defaultEndpointMode({
          port: window.location.port,
          deployProfile: health.deploy_profile,
        });
        setFallback(next);
        setProfileReady(true);
        console.info("endpoint profile=%s fallback=%s", health.deploy_profile || "-", next);
      })
      .catch((err) => {
        console.error(err);
        if (!cancelled) setProfileReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [scope]);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (readyKey !== storageKey || !rosterReady || !profileReady) return;
    const resolved = restored.current
      ? reconcileEndpoint(nodes, mode, selectedId)
      : restoreEndpoint(
          nodes,
          window.sessionStorage.getItem(modeKey) || "",
          window.sessionStorage.getItem(storageKey) || "",
          fallback,
          window.sessionStorage.getItem(pickedKey) === "1"
        );
    restored.current = true;
    if (resolved.mode === mode && resolved.deviceId === selectedId) return;
    setMode(resolved.mode);
    setSelectedId(resolved.deviceId);
    window.sessionStorage.setItem(modeKey, resolved.mode);
    if (resolved.mode !== "cloud" && resolved.deviceId) {
      window.sessionStorage.setItem(storageKey, resolved.deviceId);
    }
    console.info(
      "endpoint mode=%s device=%s fallback=%s",
      resolved.mode,
      resolved.deviceId || "-",
      fallback
    );
  }, [nodes, selectedId, mode, storageKey, modeKey, pickedKey, readyKey, rosterReady, profileReady, fallback]);

  const select = useCallback(
    (id: string) => {
      const node = nodes.find((item) => item.id === id);
      const nextMode = node ? modeOfNode(node) : mode;
      setSelectedId(id);
      setMode(nextMode);
      window.sessionStorage.setItem(storageKey, id);
      window.sessionStorage.setItem(modeKey, nextMode);
      window.sessionStorage.setItem(pickedKey, "1");
      console.info("endpoint mode=%s device=%s", nextMode, id);
    },
    [nodes, mode, storageKey, modeKey, pickedKey]
  );

  const selectMode = useCallback(
    (next: EndpointMode) => {
      const deviceId = preferredDeviceId(nodes, next, selectedId);
      setMode(next);
      setSelectedId(deviceId);
      window.sessionStorage.setItem(modeKey, next);
      window.sessionStorage.setItem(pickedKey, "1");
      if (next !== "cloud" && deviceId) window.sessionStorage.setItem(storageKey, deviceId);
      console.info("endpoint mode=%s device=%s", next, deviceId || "-");
    },
    [nodes, selectedId, storageKey, modeKey, pickedKey]
  );

  const selected = nodes.find((node) => node.id === selectedId) || null;
  const ready = readyKey === storageKey;

  return (
    <TerminalContext.Provider
      value={{ nodes, selectedId, selected, mode, ready, error, select, selectMode, refresh }}
    >
      {children}
    </TerminalContext.Provider>
  );
}

export function useTerminal() {
  const ctx = useContext(TerminalContext);
  if (!ctx) throw new Error("useTerminal must be used within TerminalProvider");
  return ctx;
}
