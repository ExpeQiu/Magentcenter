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
import type { FleetNode } from "@/lib/types";

function asAgents(value: FleetNode["agents"] | undefined | null) {
  return Array.isArray(value) ? value : [];
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
    api
      .fleetNodes(workspaceId)
      .then((list) => {
        const sorted = list
          .map(normalizeNode)
          .sort((a, b) => a.name.localeCompare(b.name, "zh"));
        setNodes(sorted);
        setError("");
      })
      .catch((err) => {
        console.error(err);
        setError("无法连接协调器");
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
    if (nodes.some((node) => node.id === selectedId)) return;
    const next = nodes[0].id;
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
