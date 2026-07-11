"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace, useWorkspacePaths } from "@/lib/context/workspace-context";
import { useModal } from "@/lib/context/modal-context";
import { AgentPicker } from "@/components/pickers/agent-picker";
import { ProjectPicker } from "@/components/pickers/project-picker";

export function CreateTaskModal() {
  const { modal, closeModal, presetAgentId, presetProjectId, openCreateTask } =
    useModal();
  const { workspaceId } = useWorkspace();
  const wp = useWorkspacePaths();
  const router = useRouter();
  const [agentId, setAgentId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [startDate, setStartDate] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (modal === "create-task") {
      setAgentId(presetAgentId);
      setProjectId(presetProjectId);
    }
  }, [modal, presetAgentId, presetProjectId]);

  useEffect(() => {
    const handler = () => openCreateTask();
    document.addEventListener("agentcenter:create-task", handler);
    return () => document.removeEventListener("agentcenter:create-task", handler);
  }, [openCreateTask]);

  if (modal !== "create-task") return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agentId || !prompt.trim()) return;
    setSubmitting(true);
    try {
      const task = await api.createTask({
        agent_id: agentId,
        prompt,
        workspace_id: workspaceId || undefined,
        project_id: projectId || undefined,
        start_date: startDate || undefined,
        due_date: dueDate || undefined,
      });
      closeModal();
      setPrompt("");
      setStartDate("");
      setDueDate("");
      router.push(wp.taskDetail(task.id));
    } catch {
      alert("创建任务失败");
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
            <label className="mb-1 block text-xs text-slate-400">Agent</label>
            <AgentPicker value={agentId} onChange={setAgentId} />
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
              disabled={submitting || !agentId || !prompt.trim()}
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
