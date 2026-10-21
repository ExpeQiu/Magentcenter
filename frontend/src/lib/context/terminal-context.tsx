"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/context/workspace-context";
import type { FleetLink, FleetNode, FleetPeer } from "@/lib/types";

function asAgents(value: FleetNode["agents"] | undefined | null) {
  return Array.isArray(value) ? value : [];
}

function asMode(mode: string | undefined): FleetNode["mode"] {
  if (mode === "local" || mode === "webhook" || mode === "plugin") return mode;
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

export function chooseTerminalId(nodes: FleetNode[], selectedId: string): string {
  if (selectedId && nodes.some((node) => node.id === selectedId)) return selectedId;
  const self = nodes.find((node) => node.self === true);
  const local = nodes.find((node) => node.mode === "local" && node.bound);
  const bound = nodes.find((node) => node.bound);
  return (self || local || bound || nodes[0])?.id || "";
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
  error: string;
  select: (id: string) => void;
  refresh: () => void;
}

const TerminalContext = createContext<TerminalContextValue | null>(null);

export function TerminalProvider({ children }: { children: ReactNode }) {
  const { workspaceId, slug } = useWorkspace();
  const storageKey = `agentcenter.terminal.${workspaceId || slug}`;
  const [nodes, setNodes] = useState<FleetNode[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [readyKey, setReadyKey] = useState("");
  const [error, setError] = useState("");

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
    setSelectedId(window.sessionStorage.getItem(storageKey) || "");
    setReadyKey(storageKey);
  }, [storageKey]);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (readyKey !== storageKey || !nodes.length) return;
    const next = chooseTerminalId(nodes, selectedId);
    if (!next || next === selectedId) return;
    setSelectedId(next);
    window.sessionStorage.setItem(storageKey, next);
    console.info("terminal default", next);
  }, [nodes, selectedId, storageKey, readyKey]);

  const select = useCallback(
    (id: string) => {
      setSelectedId(id);
      window.sessionStorage.setItem(storageKey, id);
      console.info("terminal selected", id);
    },
    [storageKey]
  );

  const selected = nodes.find((node) => node.id === selectedId) || null;

  return (
    <TerminalContext.Provider value={{ nodes, selectedId, selected, error, select, refresh }}>
      {children}
    </TerminalContext.Provider>
  );
}

export function useTerminal() {
  const ctx = useContext(TerminalContext);
  if (!ctx) throw new Error("useTerminal must be used within TerminalProvider");
  return ctx;
}
