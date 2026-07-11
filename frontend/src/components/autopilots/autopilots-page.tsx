"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { AutopilotInfo } from "@/lib/types";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { AgentPicker } from "@/components/pickers/agent-picker";
import { formatTime } from "@/components/ui/status-badge";

export function AutopilotsPage() {
  const [items, setItems] = useState<AutopilotInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [cron, setCron] = useState("3600");
  const router = useRouter();
  const wp = useWorkspacePaths();

  const load = () =>
    api
      .autopilots()
      .then(setItems)
      .catch(console.error)
      .finally(() => setLoading(false));

  useEffect(() => {
    load();
  }, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.createAutopilot({ name, agent_id: agentId, prompt, cron });
      setShowForm(false);
      setName("");
      setPrompt("");
      load();
    } catch {
      alert("创建失败");
    }
  };

  const trigger = async (id: string) => {
    try {
      const task = await api.triggerAutopilot(id);
      router.push(wp.taskDetail(task.id));
    } catch {
      alert("触发失败");
    }
  };

  return (
    <>
      <PageHeader
        title="Autopilot"
        description="定时自动触发 Agent 巡检"
        actions={
          <button
            onClick={() => setShowForm(!showForm)}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500"
          >
            + 新建
          </button>
        }
      />
      {showForm && (
        <form
          onSubmit={create}
          className="mb-6 space-y-3 rounded-xl border border-slate-800 bg-slate-900/50 p-4"
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="名称"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          />
          <AgentPicker value={agentId} onChange={setAgentId} />
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="巡检 prompt"
            rows={2}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          />
          <input
            value={cron}
            onChange={(e) => setCron(e.target.value)}
            placeholder="间隔秒数 / hourly / daily"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          />
          <button
            type="submit"
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm"
          >
            创建
          </button>
        </form>
      )}
      {loading ? (
        <p className="text-slate-500">加载中…</p>
      ) : items.length === 0 ? (
        <EmptyState title="暂无 Autopilot" description="创建定时任务自动巡检" />
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-900/80 text-left text-xs text-slate-400">
                <th className="px-4 py-3">名称</th>
                <th className="px-4 py-3">Agent</th>
                <th className="px-4 py-3">Cron</th>
                <th className="px-4 py-3">上次运行</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id} className="border-t border-slate-800/80">
                  <td className="px-4 py-3">{a.name}</td>
                  <td className="px-4 py-3 font-mono text-xs">{a.agent_id}</td>
                  <td className="px-4 py-3 text-slate-400">{a.cron}</td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {a.last_run ? formatTime(a.last_run) : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => trigger(a.id)}
                      className="text-xs text-indigo-400 hover:underline"
                    >
                      立即触发
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
