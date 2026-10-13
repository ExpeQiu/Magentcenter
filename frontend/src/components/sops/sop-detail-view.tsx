"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import type { AgentInfo, SopInfo } from "@/lib/types";

export function SopDetailView() {
  const params = useSearchParams();
  const sopId = (params.get("id") || "").trim();
  const wp = useWorkspacePaths();
  const [sop, setSop] = useState<SopInfo | null>(null);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [agentId, setAgentId] = useState("");
  const [title, setTitle] = useState("");
  const [instruction, setInstruction] = useState("");
  const [skillName, setSkillName] = useState("");
  const [taskIds, setTaskIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const reload = () => api.sop(sopId).then(setSop).catch(console.error);

  useEffect(() => {
    if (!sopId) return;
    reload();
    api
      .agents()
      .then((list) => {
        setAgents(list);
        const preferred = list.find((a) => a.is_default) || list[0];
        if (preferred) setAgentId(`${preferred.runtime}:${preferred.id}`);
      })
      .catch(console.error);
  }, [sopId]);

  const addStep = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    try {
      const next = await api.addSopStep(sopId, {
        title,
        instruction,
        skill_name: skillName,
      });
      setSop(next);
      setTitle("");
      setInstruction("");
      setSkillName("");
    } catch (err) {
      alert(err instanceof Error ? err.message : "添加失败");
    }
  };

  const move = async (index: number, dir: -1 | 1) => {
    if (!sop) return;
    const next = index + dir;
    if (next < 0 || next >= sop.steps.length) return;
    const ids = sop.steps.map((s) => s.id);
    const [item] = ids.splice(index, 1);
    ids.splice(next, 0, item);
    setSop(await api.reorderSopSteps(sopId, ids));
  };

  const remove = async (stepId: string) => {
    setSop(await api.deleteSopStep(sopId, stepId));
  };

  const run = async () => {
    if (!agentId) return;
    const [runtime, id] = agentId.split(":");
    if (!id || (runtime !== "openclaw" && runtime !== "hermes")) return;
    setBusy(true);
    try {
      const result = await api.runSop(sopId, { agent_id: id, runtime });
      setTaskIds(result.task_ids);
      await reload();
    } catch (err) {
      alert(err instanceof Error ? err.message : "运行失败");
    } finally {
      setBusy(false);
    }
  };

  if (!sop) {
    return <p className="text-slate-500">加载中…</p>;
  }

  return (
    <div>
      <Link href={wp.projects()} className="mb-4 inline-block text-sm text-indigo-400 hover:underline">
        ← 返回 SOP
      </Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{sop.name}</h1>
          {sop.description && <p className="mt-1 text-sm text-slate-400">{sop.description}</p>}
          <p className="mt-2 text-xs text-slate-500">
            {sop.step_count} 步 · 已运行 {sop.run_count} 次
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm"
          >
            {agents.length === 0 && <option value="">无可用 Agent</option>}
            {agents.map((agent) => (
              <option key={`${agent.runtime}:${agent.id}`} value={`${agent.runtime}:${agent.id}`}>
                {agent.identity_emoji ? `${agent.identity_emoji} ` : ""}
                {agent.identity_name || agent.name} · {agent.runtime}
              </option>
            ))}
          </select>
          <button
            onClick={run}
            disabled={busy || sop.steps.length === 0 || !agentId}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500 disabled:opacity-40"
          >
            {busy ? "派发中…" : "按步骤运行"}
          </button>
        </div>
      </div>

      <ol className="mb-6 space-y-2">
        {sop.steps.map((step, index) => (
          <li
            key={step.id}
            className="flex items-start gap-3 rounded-xl border border-slate-800 bg-slate-900/40 p-4"
          >
            <span className="mt-0.5 w-6 text-sm text-slate-500">{index + 1}</span>
            <div className="min-w-0 flex-1">
              <p className="font-medium">{step.title}</p>
              {step.instruction && (
                <p className="mt-1 whitespace-pre-wrap text-sm text-slate-400">{step.instruction}</p>
              )}
              {step.skill_name && (
                <p className="mt-1 text-xs text-indigo-300">技能 {step.skill_name}</p>
              )}
            </div>
            <div className="flex shrink-0 gap-1 text-xs">
              <button
                type="button"
                onClick={() => move(index, -1)}
                className="rounded px-2 py-1 text-slate-400 hover:bg-slate-800"
              >
                上移
              </button>
              <button
                type="button"
                onClick={() => move(index, 1)}
                className="rounded px-2 py-1 text-slate-400 hover:bg-slate-800"
              >
                下移
              </button>
              <button
                type="button"
                onClick={() => remove(step.id)}
                className="rounded px-2 py-1 text-rose-300 hover:bg-slate-800"
              >
                删除
              </button>
            </div>
          </li>
        ))}
      </ol>

      <form onSubmit={addStep} className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <p className="text-sm font-medium text-slate-300">添加步骤</p>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="步骤标题"
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
        />
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder="这一步要做什么"
          rows={3}
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
        />
        <input
          value={skillName}
          onChange={(e) => setSkillName(e.target.value)}
          placeholder="技能名（可选）"
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
        />
        <button type="submit" className="rounded-lg bg-slate-700 px-4 py-2 text-sm hover:bg-slate-600">
          加入流程
        </button>
      </form>

      {taskIds.length > 0 && (
        <div className="mt-6 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4">
          <p className="text-sm text-emerald-200">已按步骤创建 {taskIds.length} 个任务</p>
          <ul className="mt-2 space-y-1 text-sm">
            {taskIds.map((id, index) => (
              <li key={id}>
                <Link href={wp.taskDetail(id)} className="text-indigo-300 hover:underline">
                  第 {index + 1} 步任务
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
