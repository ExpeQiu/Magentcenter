"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace, useWorkspacePaths } from "@/lib/context/workspace-context";
import { useTerminal } from "@/lib/context/terminal-context";
import { useModal } from "@/lib/context/modal-context";
import {
  AgentPicker,
  agentRefKey,
  parseAgentRef,
} from "@/components/pickers/agent-picker";
import { ProjectPicker } from "@/components/pickers/project-picker";
import type { AgentInfo, RuntimeName } from "@/lib/types";

function taskAgentRef(agent: AgentInfo): string {
  if (agent.node_id) return `node:${agent.node_id}:${agent.runtime}:${agent.id}`;
  return agentRefKey(agent);
}

function decodeTaskAgent(value: string): {
  nodeId?: string;
  runtime: RuntimeName;
  agentId: string;
} {
  if (value.startsWith("node:")) {
    const [, nodeId, runtime, ...rest] = value.split(":");
    return {
      nodeId,
      runtime: (runtime || "openclaw") as RuntimeName,
      agentId: rest.join(":"),
    };
  }
  return parseAgentRef(value);
}

export function CreateTaskModal() {
  const { modal, closeModal, presetAgentId, presetProjectId, openCreateTask } =
    useModal();
  const { workspaceId } = useWorkspace();
  const { selected: terminal } = useTerminal();
  const wp = useWorkspacePaths();
  const router = useRouter();
  const [agentRef, setAgentRef] = useState("");
  const [projectId, setProjectId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [startDate, setStartDate] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [agents, setAgents] = useState<AgentInfo[]>([]);

  useEffect(() => {
    if (modal === "create-task") {
      setAgentRef(presetAgentId);
      setProjectId(presetProjectId);
    }
  }, [modal, presetAgentId, presetProjectId]);

  useEffect(() => {
    const handler = () => openCreateTask();
    document.addEventListener("agentcenter:create-task", handler);
    return () => document.removeEventListener("agentcenter:create-task", handler);
  }, [openCreateTask]);

  useEffect(() => {
    if (modal !== "create-task") return;
    api
      .agents()
      .then((local) => {
        const bound: AgentInfo[] = [];
        if (terminal?.bound) {
          for (const agent of terminal.agents) {
            bound.push({
              id: agent.id,
              name: agent.name,
              model: agent.model || "",
              workspace: "",
              identity_name: agent.name,
              identity_emoji: "",
              is_default: false,
              runtime: agent.runtime,
              node_id: terminal.id,
              node_name: terminal.name,
            });
          }
        }
        setAgents([...bound, ...local]);
        console.info(
          "task agents loaded terminal=%s bound=%d local=%d",
          terminal?.id || "-",
          bound.length,
          local.length
        );
      })
      .catch((err) => {
        console.error(err);
      });
  }, [modal, terminal]);

  if (modal !== "create-task") return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agentRef || !prompt.trim()) return;
    const { runtime, agentId, nodeId } = decodeTaskAgent(agentRef);
    if (!agentId) return;
    setSubmitting(true);
    try {
      const task = await api.createTask({
        agent_id: agentId,
        runtime,
        prompt,
        node_id: nodeId,
        workspace_id: workspaceId || undefined,
        project_id: projectId || undefined,
        start_date: startDate || undefined,
        due_date: dueDate || undefined,
      });
      console.info("task created id=%s node=%s agent=%s", task.id, nodeId || "-", agentId);
      closeModal();
      setPrompt("");
      setStartDate("");
      setDueDate("");
      router.push(wp.taskDetail(task.id));
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : "创建任务失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-xl border border-slate-700 bg-slate-900 p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">新建任务</h2>
          <button
            onClick={closeModal}
            className="text-slate-400 hover:text-slate-200"
          >
            ✕
          </button>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="mb-1 block text-xs text-slate-400">项目</label>
            <ProjectPicker value={projectId} onChange={setProjectId} />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-400">
              Agent（含 OpenClaw / Hermes）
            </label>
            <AgentPicker
              value={agentRef}
              agents={agents}
              refKey={taskAgentRef}
              onChange={(ref) => setAgentRef(ref)}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-400">任务描述</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={4}
              placeholder="描述要分配给 Agent 的任务…"
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs text-slate-400">开始日期</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-400">截止日期</label>
              <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={closeModal}
              className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:text-slate-200"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={submitting || !agentRef || !prompt.trim()}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
            >
              {submitting ? "提交中…" : "分配任务"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
