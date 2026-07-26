"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { SkillDetail, SkillInfo, TaskInfo } from "@/lib/types";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";

type AuditVerdict = "pass" | "revise" | "reject" | "pending";

interface AuditRecord {
  verdict: AuditVerdict;
  taskId: string;
  updatedAt: string;
}

type AuditMap = Record<string, AuditRecord>;

const AUDIT_STORAGE_KEY = "agentcenter.skill-audits";

function loadAudits(): AuditMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(AUDIT_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as AuditMap) : {};
  } catch {
    return {};
  }
}

function saveAudits(map: AuditMap) {
  localStorage.setItem(AUDIT_STORAGE_KEY, JSON.stringify(map));
}

function parseVerdict(output: string): AuditVerdict | null {
  const m = output.match(/结论\s*[:：]\s*(通过|需修改|拒绝)/);
  if (!m) return null;
  if (m[1] === "通过") return "pass";
  if (m[1] === "需修改") return "revise";
  return "reject";
}

function verdictLabel(v: AuditVerdict): string {
  switch (v) {
    case "pass":
      return "通过";
    case "revise":
      return "需修改";
    case "reject":
      return "拒绝";
    default:
      return "审核中";
  }
}

function verdictClass(v: AuditVerdict): string {
  switch (v) {
    case "pass":
      return "bg-emerald-500/15 text-emerald-300";
    case "revise":
      return "bg-amber-500/15 text-amber-300";
    case "reject":
      return "bg-rose-500/15 text-rose-300";
    default:
      return "bg-slate-700/60 text-slate-300";
  }
}

function isTerminal(status: string): boolean {
  return ["completed", "failed", "cancelled", "error"].includes(status);
}

export function SkillsPage() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [filter, setFilter] = useState("");
  const [ownerFilter, setOwnerFilter] = useState("all");
  const [modeFilter, setModeFilter] = useState<"all" | "auto" | "manual">("all");
  const [runtimeFilter, setRuntimeFilter] = useState<"all" | "openclaw" | "hermes">(
    "all"
  );
  const [includeArchived, setIncludeArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [installUrl, setInstallUrl] = useState("");
  const [installRuntime, setInstallRuntime] = useState<"openclaw" | "hermes">(
    "openclaw"
  );
  const [showInstall, setShowInstall] = useState(false);
  const [installTask, setInstallTask] = useState<TaskInfo | null>(null);
  const [installMsg, setInstallMsg] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedRuntime, setSelectedRuntime] = useState<"openclaw" | "hermes">(
    "openclaw"
  );
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [audits, setAudits] = useState<AuditMap>({});
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const router = useRouter();
  const wp = useWorkspacePaths();

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    try {
      const list = await api.skills({
        includeArchived,
        runtime: runtimeFilter,
      });
      setSkills(list);
    } catch (err) {
      console.error("skills load failed", err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [includeArchived, runtimeFilter]);

  useEffect(() => {
    setAudits(loadAudits());
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    api
      .skillDetail(selectedId, selectedRuntime)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((err) => {
        console.error("skill detail failed", err);
        if (!cancelled) setDetail(null);
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, selectedRuntime]);

  // 轮询安装任务
  useEffect(() => {
    if (!installTask || isTerminal(installTask.status)) return;
    const timer = setInterval(async () => {
      try {
        const t = await api.task(installTask.id);
        setInstallTask(t);
        if (t.status === "completed") {
          load(true);
        }
      } catch (err) {
        console.error("install task poll failed", err);
      }
    }, 2500);
    return () => clearInterval(timer);
  }, [installTask, load]);

  // 轮询审核中任务
  useEffect(() => {
    const pending = Object.entries(audits).filter(([, r]) => r.verdict === "pending");
    if (pending.length === 0) return;
    const timer = setInterval(async () => {
      let changed = false;
      const next = { ...audits };
      for (const [skillId, rec] of pending) {
        try {
          const t = await api.task(rec.taskId);
          if (!isTerminal(t.status)) continue;
          const verdict =
            t.status === "completed"
              ? parseVerdict(t.output || "") || "revise"
              : "reject";
          next[skillId] = {
            verdict,
            taskId: rec.taskId,
            updatedAt: new Date().toISOString(),
          };
          changed = true;
        } catch (err) {
          console.error("audit poll failed", skillId, err);
        }
      }
      if (changed) {
        setAudits(next);
        saveAudits(next);
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [audits]);

  const owners = useMemo(() => {
    const set = new Set<string>();
    for (const s of skills) {
      if (s.owner) set.add(s.owner);
    }
    return Array.from(set).sort();
  }, [skills]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return skills.filter((s) => {
      if (runtimeFilter !== "all" && (s.runtime || "openclaw") !== runtimeFilter)
        return false;
      if (ownerFilter !== "all" && (s.owner || "") !== ownerFilter) return false;
      if (modeFilter === "auto" && s.disable_model_invocation) return false;
      if (modeFilter === "manual" && !s.disable_model_invocation) return false;
      if (!q) return true;
      const hay = [
        s.id,
        s.name,
        s.runtime || "",
        s.description,
        s.description_full || "",
        s.owner || "",
        ...(s.allowed_tools || []),
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [skills, filter, ownerFilter, modeFilter, runtimeFilter]);

  const install = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionBusy("install");
    setInstallMsg("");
    try {
      const result = await api.installSkill({
        url: installUrl,
        runtime: installRuntime,
      });
      if (result.task) {
        setInstallTask(result.task);
      } else {
        setInstallTask(null);
        setInstallMsg(
          `[${result.runtime}] ${result.status}: ${result.message || result.identifier}`
        );
      }
      setShowInstall(false);
      setInstallUrl("");
      if (result.runtime === "hermes" && result.status === "completed") {
        await load(true);
      }
    } catch {
      alert("安装失败");
    } finally {
      setActionBusy(null);
    }
  };

  const audit = async (skillId: string) => {
    setActionBusy(`audit:${skillId}`);
    try {
      const task = await api.auditSkill(skillId);
      const next = {
        ...audits,
        [skillId]: {
          verdict: "pending" as const,
          taskId: task.id,
          updatedAt: new Date().toISOString(),
        },
      };
      setAudits(next);
      saveAudits(next);
    } catch {
      alert("审核任务创建失败");
    } finally {
      setActionBusy(null);
    }
  };

  const archive = async (skillId: string, runtime: "openclaw" | "hermes" = "openclaw") => {
    if (!confirm(`确认下线技能 ${skillId}（${runtime}）？将移动到 _archive/`)) return;
    setActionBusy(`archive:${skillId}`);
    try {
      await api.archiveSkill(skillId, runtime);
      if (selectedId === skillId) setSelectedId(null);
      await load(true);
    } catch (err) {
      console.error(err);
      alert("下线失败");
    } finally {
      setActionBusy(null);
    }
  };

  return (
    <>
      <PageHeader
        title="技能目录"
        description={`OpenClaw / Hermes 已扫描 ${skills.length} · 展示 ${filtered.length}`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={runtimeFilter}
              onChange={(e) =>
                setRuntimeFilter(e.target.value as "all" | "openclaw" | "hermes")
              }
              className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm"
            >
              <option value="all">全部运行时</option>
              <option value="openclaw">OpenClaw</option>
              <option value="hermes">Hermes</option>
            </select>
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="搜索 id / 名称 / 描述 / owner…"
              className="w-52 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm"
            />
            <select
              value={ownerFilter}
              onChange={(e) => setOwnerFilter(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm"
            >
              <option value="all">全部 owner</option>
              {owners.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
            <select
              value={modeFilter}
              onChange={(e) =>
                setModeFilter(e.target.value as "all" | "auto" | "manual")
              }
              className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm"
            >
              <option value="all">触发模式</option>
              <option value="auto">可自动调用</option>
              <option value="manual">仅手动</option>
            </select>
            <label className="flex items-center gap-1.5 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={includeArchived}
                onChange={(e) => setIncludeArchived(e.target.checked)}
              />
              含归档
            </label>
            <button
              onClick={() => load(true)}
              disabled={refreshing}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800 disabled:opacity-50"
            >
              {refreshing ? "刷新中…" : "刷新"}
            </button>
            <button
              onClick={() => setShowInstall(!showInstall)}
              className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500"
            >
              安装
            </button>
          </div>
        }
      />

      {installMsg && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 text-sm">
          <p className="text-slate-300">{installMsg}</p>
          <button
            onClick={() => setInstallMsg("")}
            className="text-slate-500 hover:text-slate-300"
          >
            关闭
          </button>
        </div>
      )}

      {installTask && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 text-sm">
          <div>
            <span className="text-slate-400">安装任务 </span>
            <span className="font-mono text-slate-200">{installTask.id.slice(0, 8)}</span>
            <span className="ml-2 text-slate-500">状态 {installTask.status}</span>
            {installTask.error && (
              <span className="ml-2 text-rose-400">{installTask.error}</span>
            )}
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => router.push(wp.taskDetail(installTask.id))}
              className="text-indigo-400 hover:underline"
            >
              查看任务
            </button>
            {isTerminal(installTask.status) && (
              <button
                onClick={() => setInstallTask(null)}
                className="text-slate-500 hover:text-slate-300"
              >
                关闭
              </button>
            )}
          </div>
        </div>
      )}

      {showInstall && (
        <form
          onSubmit={install}
          className="mb-6 flex flex-wrap gap-2 rounded-xl border border-slate-800 bg-slate-900/50 p-4"
        >
          <select
            value={installRuntime}
            onChange={(e) =>
              setInstallRuntime(e.target.value as "openclaw" | "hermes")
            }
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-2 text-sm"
          >
            <option value="openclaw">OpenClaw（skill-agent）</option>
            <option value="hermes">Hermes（CLI install）</option>
          </select>
          <input
            value={installUrl}
            onChange={(e) => setInstallUrl(e.target.value)}
            placeholder={
              installRuntime === "hermes"
                ? "标识或 URL，如 openai/skills/skill-creator"
                : "技能 URL 或名称"
            }
            className="min-w-[220px] flex-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
            required
          />
          <button
            type="submit"
            disabled={actionBusy === "install"}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm disabled:opacity-50"
          >
            提交安装
          </button>
        </form>
      )}

      {loading ? (
        <p className="text-slate-500">加载中…</p>
      ) : filtered.length === 0 ? (
        <EmptyState title="未找到技能" description="调整筛选条件或刷新目录" />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((s) => {
            const rt = (s.runtime || "openclaw") as "openclaw" | "hermes";
            const auditRec = audits[`${rt}:${s.id}`] || audits[s.id];
            return (
              <div
                key={`${rt}:${s.id}`}
                className="group flex cursor-pointer flex-col rounded-xl border border-slate-800 bg-slate-900/40 p-4 transition hover:border-indigo-500/40"
                onClick={() => {
                  setSelectedRuntime(rt);
                  setSelectedId(s.id);
                }}
              >
                <div className="mb-1 flex items-start justify-between gap-2">
                  <p className="text-sm font-medium text-slate-100">
                    {s.emoji ? `${s.emoji} ` : ""}
                    {s.name}
                  </p>
                  <div className="flex shrink-0 flex-wrap justify-end gap-1">
                    <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase text-slate-400">
                      {rt}
                    </span>
                    {s.archived && (
                      <span className="rounded bg-slate-700/80 px-1.5 py-0.5 text-[10px] text-slate-300">
                        已归档
                      </span>
                    )}
                    {s.disable_model_invocation ? (
                      <span className="rounded bg-slate-700/50 px-1.5 py-0.5 text-[10px] text-slate-400">
                        手动
                      </span>
                    ) : (
                      <span className="rounded bg-indigo-500/15 px-1.5 py-0.5 text-[10px] text-indigo-300">
                        自动
                      </span>
                    )}
                    {auditRec && (
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] ${verdictClass(auditRec.verdict)}`}
                      >
                        {verdictLabel(auditRec.verdict)}
                      </span>
                    )}
                  </div>
                </div>
                <p className="font-mono text-[11px] text-slate-500">{s.id}</p>
                {s.description && (
                  <p className="mt-2 line-clamp-2 text-xs text-slate-400">
                    {s.description}
                  </p>
                )}
                <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500">
                  {s.owner && <span>owner: {s.owner}</span>}
                  {s.version && <span>v{s.version}</span>}
                  {(s.allowed_tools?.length ?? 0) > 0 && (
                    <span>{s.allowed_tools!.length} tools</span>
                  )}
                </div>
                <div
                  className="mt-3 flex gap-3 text-xs opacity-0 transition group-hover:opacity-100"
                  onClick={(e) => e.stopPropagation()}
                >
                  {!s.archived && (
                    <>
                      <button
                        onClick={() => audit(s.id)}
                        disabled={actionBusy === `audit:${s.id}`}
                        className="text-indigo-400 hover:underline disabled:opacity-50"
                      >
                        审核
                      </button>
                      <button
                        onClick={() => archive(s.id, rt)}
                        disabled={actionBusy === `archive:${s.id}`}
                        className="text-slate-400 hover:text-rose-300 disabled:opacity-50"
                      >
                        下线
                      </button>
                    </>
                  )}
                  {auditRec && (
                    <button
                      onClick={() => router.push(wp.taskDetail(auditRec.taskId))}
                      className="text-slate-500 hover:underline"
                    >
                      审核任务
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {selectedId && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={() => setSelectedId(null)}>
          <aside
            className="h-full w-full max-w-lg overflow-y-auto border-l border-slate-800 bg-slate-950 p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-slate-100">
                  {detail?.emoji ? `${detail.emoji} ` : ""}
                  {detail?.name || selectedId}
                </h2>
                <p className="mt-1 font-mono text-xs text-slate-500">{selectedId}</p>
              </div>
              <button
                onClick={() => setSelectedId(null)}
                className="rounded-lg border border-slate-700 px-2 py-1 text-sm text-slate-400 hover:bg-slate-800"
              >
                关闭
              </button>
            </div>

            {detailLoading || !detail ? (
              <p className="text-sm text-slate-500">加载详情…</p>
            ) : (
              <>
                <p className="text-sm leading-relaxed text-slate-300">
                  {detail.description_full || detail.description || "无描述"}
                </p>
                <dl className="mt-4 grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <dt className="text-slate-500">owner</dt>
                    <dd className="text-slate-200">{detail.owner || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">version</dt>
                    <dd className="text-slate-200">{detail.version || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">触发</dt>
                    <dd className="text-slate-200">
                      {detail.disable_model_invocation ? "仅手动" : "可自动调用"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">状态</dt>
                    <dd className="text-slate-200">
                      {detail.archived ? "已归档" : "已安装"}
                    </dd>
                  </div>
                </dl>
                {(detail.allowed_tools?.length ?? 0) > 0 && (
                  <div className="mt-4">
                    <p className="mb-1 text-xs text-slate-500">allowed-tools</p>
                    <div className="flex flex-wrap gap-1">
                      {detail.allowed_tools!.map((t) => (
                        <span
                          key={t}
                          className="rounded bg-slate-800 px-2 py-0.5 font-mono text-[11px] text-slate-300"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                <p className="mt-4 break-all font-mono text-[11px] text-slate-600">
                  {detail.path}
                </p>
                <div className="mt-4 flex gap-2">
                  {!detail.archived && (
                    <>
                      <button
                        onClick={() => audit(detail.id)}
                        className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500"
                      >
                        审核
                      </button>
                      <button
                        onClick={() => archive(detail.id, selectedRuntime)}
                        className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:border-rose-500/50 hover:text-rose-300"
                      >
                        下线
                      </button>
                    </>
                  )}
                </div>
                {detail.body_preview && (
                  <pre className="mt-5 max-h-[50vh] overflow-auto rounded-xl border border-slate-800 bg-slate-900/70 p-3 text-xs leading-relaxed text-slate-400 whitespace-pre-wrap">
                    {detail.body_preview}
                  </pre>
                )}
              </>
            )}
          </aside>
        </div>
      )}
    </>
  );
}
