"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { AutopilotInfo } from "@/lib/types";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import {
  AgentPicker,
  parseAgentRef,
} from "@/components/pickers/agent-picker";
import { StatusBadge, formatTime } from "@/components/ui/status-badge";
import { TimelineView } from "@/components/autopilots/timeline-view";

type ViewMode = "list" | "timeline";

function sourceLabel(a: AutopilotInfo) {
  if (a.source === "hermes" || a.id.startsWith("hermes:")) return "Hermes";
  if (a.source === "openclaw" || a.id.startsWith("openclaw:")) return "OpenClaw";
  if (a.source === "bidirectional") return "双向";
  return "本地";
}

export function AutopilotsPage() {
  const [items, setItems] = useState<AutopilotInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [view, setView] = useState<ViewMode>("list");
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [agentRef, setAgentRef] = useState("");
  const [prompt, setPrompt] = useState("");
  const [cron, setCron] = useState("3600");
  const [syncExternal, setSyncExternal] = useState(false);
  const router = useRouter();
  const wp = useWorkspacePaths();

  const load = (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    const req = isRefresh
      ? api.refreshAutopilots().then((data) => {
          setItems(data.items);
          console.info(
            "[autopilot] reconciled count=%d pruned=%d synced_oc=%d synced_hm=%d",
            data.count,
            data.pruned_count,
            data.synced_openclaw,
            data.synced_hermes,
          );
        })
      : api.autopilots(true, true).then((data) => {
          setItems(data);
        });
    return req
      .catch(console.error)
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
      });
  };

  useEffect(() => {
    void load();
  }, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agentRef) return;
    const { runtime, agentId } = parseAgentRef(agentRef);
    try {
      await api.createAutopilot({
        name,
        agent_id: agentId,
        runtime,
        prompt,
        cron,
        sync_to_openclaw: syncExternal && runtime === "openclaw",
        sync_to_hermes: syncExternal && runtime === "hermes",
      });
      setShowForm(false);
      setName("");
      setPrompt("");
      setAgentRef("");
      load();
    } catch {
      alert("创建失败");
    }
  };

  const trigger = async (id: string) => {
    try {
      const task = await api.triggerAutopilot(id);
      if (id.startsWith("openclaw:") || id.startsWith("hermes:")) {
        alert(`${id.startsWith("hermes:") ? "Hermes" : "OpenClaw"} Cron 已触发`);
        load();
      } else {
        router.push(wp.taskDetail(task.id));
      }
    } catch {
      alert("触发失败");
    }
  };

  return (
    <>
      <PageHeader
        title="Autopilot"
        description="本地定时 + OpenClaw / Hermes Cron 聚合"
        actions={
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-slate-700 p-0.5 text-sm">
              <button
                type="button"
                onClick={() => setView("list")}
                className={`rounded-md px-3 py-1.5 ${
                  view === "list"
                    ? "bg-indigo-500/20 text-indigo-200"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                列表
              </button>
              <button
                type="button"
                onClick={() => setView("timeline")}
                className={`rounded-md px-3 py-1.5 ${
                  view === "timeline"
                    ? "bg-indigo-500/20 text-indigo-200"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                时间轴
              </button>
            </div>
            <button
              onClick={() => setShowForm(!showForm)}
              className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500"
            >
              + 新建
            </button>
            <button
              type="button"
              onClick={() => void load(true)}
              disabled={refreshing || loading}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800 disabled:opacity-50"
              title="按 OpenClaw / Hermes 现况对账本地列表（删除外部已清掉的镜像）"
            >
              {refreshing ? "对账中…" : "刷新"}
            </button>
          </div>
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
          <AgentPicker value={agentRef} onChange={(ref) => setAgentRef(ref)} />
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
            placeholder="间隔秒数 / hourly / daily / cron 表达式"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          />
          <label className="flex items-center gap-2 text-sm text-slate-400">
            <input
              type="checkbox"
              checked={syncExternal}
              onChange={(e) => setSyncExternal(e.target.checked)}
            />
            同步到所选运行时的外部 Cron（OpenClaw / Hermes）
          </label>
          <button type="submit" className="rounded-lg bg-indigo-600 px-4 py-2 text-sm">
            创建
          </button>
        </form>
      )}
      {loading ? (
        <p className="text-slate-500">加载中…</p>
      ) : items.length === 0 ? (
        <EmptyState title="暂无 Autopilot" description="创建定时任务自动巡检" />
      ) : view === "timeline" ? (
        <TimelineView items={items} onTrigger={trigger} />
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-900/80 text-left text-xs text-slate-400">
                <th className="px-4 py-3">名称</th>
                <th className="px-4 py-3">运行时</th>
                <th className="px-4 py-3">来源</th>
                <th className="px-4 py-3">Agent</th>
                <th className="px-4 py-3">调度</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3">上次运行</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id} className="border-t border-slate-800/80">
                  <td className="px-4 py-3">{a.name}</td>
                  <td className="px-4 py-3 text-xs uppercase text-slate-500">
                    {a.runtime || (a.id.startsWith("hermes:") ? "hermes" : "openclaw")}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">{sourceLabel(a)}</td>
                  <td className="px-4 py-3 font-mono text-xs">{a.agent_id}</td>
                  <td className="px-4 py-3 text-slate-400">{a.schedule || a.cron}</td>
                  <td className="px-4 py-3">
                    {a.status ? <StatusBadge status={a.status} /> : "—"}
                  </td>
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
