"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { RecentAlert, SystemStatus } from "@/lib/types";
import { PageHeader } from "@/components/layout/page-header";
import { StatusBadge, formatTime } from "@/components/ui/status-badge";

export function SystemPage() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [alerts, setAlerts] = useState<RecentAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = (refresh = false) => {
    setLoading(true);
    setError("");
    Promise.all([
      api.systemStatus(refresh),
      api.recentAlerts(),
    ])
      .then(([s, a]) => {
        setStatus(s);
        setAlerts(a.recent_alerts ?? []);
      })
      .catch((e) => {
        console.error(e);
        setError("无法连接后端 API，请确认 AgentCenter 已启动");
        setStatus(null);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    const t = setInterval(() => load(), 30000);
    return () => clearInterval(t);
  }, []);

  const gw = status?.gateway;

  return (
    <>
      <PageHeader
        title="系统状态"
        description="OpenClaw Gateway / Cron / 告警"
        actions={
          <button
            onClick={() => load(true)}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
          >
            刷新
          </button>
        }
      />
      {loading && !status ? (
        <p className="text-slate-500">加载中…</p>
      ) : error ? (
        <div className="rounded-xl border border-amber-800/50 bg-amber-950/30 p-4 text-sm text-amber-200">
          {error}
          <p className="mt-2 text-xs text-slate-400">
            运行 <code className="text-amber-100">./scripts/start-all.sh</code> 启动服务
          </p>
        </div>
      ) : status ? (
        <div className="space-y-6">
          <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <p className="text-xs text-slate-500">Gateway</p>
              <p className="mt-1 flex items-center gap-2 text-lg font-medium">
                <span
                  className={`h-2.5 w-2.5 rounded-full ${
                    gw?.running ? "bg-emerald-400" : "bg-red-400"
                  }`}
                />
                {gw?.running ? "运行中" : "离线"}
              </p>
              <p className="mt-2 text-xs text-slate-400">
                PID {gw?.pid || "—"} · 端口 {gw?.port}
              </p>
              {gw?.dashboard_url && (
                <a
                  href={gw.dashboard_url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-block text-xs text-indigo-400 hover:underline"
                >
                  打开 OpenClaw Dashboard →
                </a>
              )}
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <p className="text-xs text-slate-500">Cron 任务</p>
              <p className="mt-1 text-lg font-medium">{status.cron_jobs.length}</p>
              <p className="mt-2 text-xs text-red-400">
                {status.cron_errors.length} 条错误
              </p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <p className="text-xs text-slate-500">Sessions</p>
              <p className="mt-1 text-lg font-medium">{status.sessions_count}</p>
              <p className="mt-2 text-xs text-slate-400">
                更新于 {formatTime(status.checked_at)}
              </p>
            </div>
          </section>

          {status.cron_errors.length > 0 && (
            <section>
              <h2 className="mb-3 text-sm font-medium text-red-300">Cron 错误</h2>
              <div className="overflow-hidden rounded-xl border border-red-900/40">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-800 bg-red-950/30 text-left text-xs text-slate-400">
                      <th className="px-4 py-3">名称</th>
                      <th className="px-4 py-3">Agent</th>
                      <th className="px-4 py-3">状态</th>
                      <th className="px-4 py-3">上次运行</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.cron_errors.map((j) => (
                      <tr key={j.id} className="border-t border-slate-800/80">
                        <td className="px-4 py-3">{j.name}</td>
                        <td className="px-4 py-3 font-mono text-xs">{j.agent_id}</td>
                        <td className="px-4 py-3">
                          <StatusBadge status={j.status || j.last_status || "error"} />
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500">
                          {j.last_run ? formatTime(j.last_run) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <section>
            <h2 className="mb-3 text-sm font-medium text-slate-300">全部 Cron</h2>
            <div className="overflow-hidden rounded-xl border border-slate-800">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-800 bg-slate-900/80 text-left text-xs text-slate-400">
                    <th className="px-4 py-3">名称</th>
                    <th className="px-4 py-3">Agent</th>
                    <th className="px-4 py-3">调度</th>
                    <th className="px-4 py-3">状态</th>
                  </tr>
                </thead>
                <tbody>
                  {status.cron_jobs.map((j) => (
                    <tr key={j.id} className="border-t border-slate-800/80">
                      <td className="px-4 py-3">{j.name}</td>
                      <td className="px-4 py-3 font-mono text-xs">{j.agent_id}</td>
                      <td className="px-4 py-3 text-xs text-slate-500">{j.schedule}</td>
                      <td className="px-4 py-3">
                        <StatusBadge status={j.status || j.last_status || "idle"} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-medium text-slate-300">告警历史</h2>
            {alerts.length === 0 ? (
              <p className="rounded-xl border border-slate-800 bg-slate-900/30 p-4 text-sm text-slate-500">
                暂无告警记录
              </p>
            ) : (
              <div className="overflow-hidden rounded-xl border border-slate-800">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-800 bg-slate-900/80 text-left text-xs text-slate-400">
                      <th className="px-4 py-3">时间</th>
                      <th className="px-4 py-3">告警数</th>
                      <th className="px-4 py-3">涉及任务</th>
                      <th className="px-4 py-3">飞书推送</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alerts.map((a, i) => (
                      <tr key={i} className="border-t border-slate-800/80">
                        <td className="px-4 py-3 text-xs text-slate-400">
                          {a.at ? formatTime(a.at) : "—"}
                        </td>
                        <td className="px-4 py-3">
                          <span className="rounded bg-red-500/15 px-2 py-0.5 text-xs text-red-300">
                            {a.count} 条
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-400">
                          {a.jobs.join(", ")}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`text-xs ${a.sent ? "text-emerald-400" : "text-red-400"}`}
                          >
                            {a.sent ? "✓ 已发送" : "✗ 失败"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      ) : (
        <p className="text-slate-500">无法获取系统状态</p>
      )}
    </>
  );
}
