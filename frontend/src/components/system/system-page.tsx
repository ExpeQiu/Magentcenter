"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useWorkspace, useWorkspacePaths } from "@/lib/context/workspace-context";
import type { AlertSettings, RecentAlert, SystemStatus } from "@/lib/types";
import { PageHeader } from "@/components/layout/page-header";
import { StatusBadge, formatTime } from "@/components/ui/status-badge";

export function SystemPage() {
  const router = useRouter();
  const wp = useWorkspacePaths();
  const { workspaceId } = useWorkspace();
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [alerts, setAlerts] = useState<RecentAlert[]>([]);
  const [alertSettings, setAlertSettings] = useState<AlertSettings | null>(null);
  const [webhookDraft, setWebhookDraft] = useState("");
  const [intervalDraft, setIntervalDraft] = useState(300);
  const [diskDraft, setDiskDraft] = useState(90);
  const [cronEnabled, setCronEnabled] = useState(true);
  const [gatewayEnabled, setGatewayEnabled] = useState(true);
  const [alertProfile, setAlertProfile] = useState("default");
  const [profileList, setProfileList] = useState<string[]>(["default"]);
  const [newProfile, setNewProfile] = useState("");
  const [savingAlert, setSavingAlert] = useState(false);
  const [alertSaveMsg, setAlertSaveMsg] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [repairingId, setRepairingId] = useState("");
  const [repairMsg, setRepairMsg] = useState("");

  const load = (refresh = false) => {
    setLoading(true);
    setError("");
    Promise.all([
      api.systemStatus(refresh),
      api.recentAlerts(),
      api.alertSettings(),
    ])
      .then(([s, a, settings]) => {
        setStatus(s);
        setAlerts(a.recent_alerts ?? []);
        setAlertSettings(settings);
        setIntervalDraft(settings.cron_alert_interval);
        setDiskDraft(settings.disk_alert_threshold);
        setCronEnabled(settings.cron_alert_enabled);
        setGatewayEnabled(settings.gateway_alert_enabled);
        setAlertProfile(settings.profile || "default");
        setProfileList(settings.profiles?.length ? settings.profiles : ["default"]);
        setWebhookDraft("");
      })
      .catch((e) => {
        console.error(e);
        setError("无法连接后端 API，请确认 AgentCenter 已启动");
        setStatus(null);
      })
      .finally(() => setLoading(false));
  };

  const applySettingsToForm = (settings: AlertSettings) => {
    setAlertSettings(settings);
    setIntervalDraft(settings.cron_alert_interval);
    setDiskDraft(settings.disk_alert_threshold);
    setCronEnabled(settings.cron_alert_enabled);
    setGatewayEnabled(settings.gateway_alert_enabled);
    setAlertProfile(settings.profile || "default");
    setProfileList(settings.profiles?.length ? settings.profiles : ["default"]);
  };

  const saveAlertRules = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingAlert(true);
    setAlertSaveMsg("");
    try {
      const body: Parameters<typeof api.updateAlertSettings>[0] = {
        cron_alert_interval: intervalDraft,
        cron_alert_enabled: cronEnabled,
        gateway_alert_enabled: gatewayEnabled,
        disk_alert_threshold: diskDraft,
        profile: alertProfile || "default",
        activate: true,
      };
      if (webhookDraft.trim()) {
        body.feishu_webhook_url = webhookDraft.trim();
      }
      const res = await api.updateAlertSettings(body);
      applySettingsToForm(res.settings);
      setWebhookDraft("");
      setAlertSaveMsg(
        `已保存到环境 ${res.profile || alertProfile} · alert_profiles.json`
      );
    } catch (err) {
      console.error(err);
      setAlertSaveMsg(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSavingAlert(false);
    }
  };

  const switchProfile = async (name: string) => {
    setSavingAlert(true);
    setAlertSaveMsg("");
    try {
      const res = await api.activateAlertProfile(name);
      applySettingsToForm(res.settings);
      setAlertSaveMsg(`已切换到环境 ${res.active}`);
    } catch (err) {
      console.error(err);
      setAlertSaveMsg(err instanceof Error ? err.message : "切换失败");
    } finally {
      setSavingAlert(false);
    }
  };

  const createProfile = async () => {
    const name = newProfile.trim();
    if (!name) return;
    setSavingAlert(true);
    setAlertSaveMsg("");
    try {
      const res = await api.createAlertProfile({
        name,
        from_current: true,
        activate: true,
      });
      applySettingsToForm(res.settings);
      setNewProfile("");
      setAlertSaveMsg(`已创建并激活环境 ${name}`);
    } catch (err) {
      console.error(err);
      setAlertSaveMsg(err instanceof Error ? err.message : "创建失败");
    } finally {
      setSavingAlert(false);
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(() => load(), 30000);
    return () => clearInterval(t);
  }, []);

  const repairCron = async (cronId: string, name: string) => {
    if (repairingId) return;
    setRepairingId(cronId);
    setRepairMsg("");
    try {
      const task = await api.repairCron(cronId, {
        workspace_id: workspaceId || undefined,
        note: `来自 System 页派单修复：${name}`,
      });
      setRepairMsg(`已派单给 ops-agent：${task.id.slice(0, 8)}…`);
      router.push(wp.taskDetail(task.id));
    } catch (e) {
      console.error(e);
      setRepairMsg(e instanceof Error ? e.message : "派单失败");
    } finally {
      setRepairingId("");
    }
  };

  const gw = status?.gateway;

  return (
    <>
      <PageHeader
        title="系统状态"
        description="OpenClaw / Hermes 双栈 Gateway · Cron · 告警"
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
          {(status.runtimes?.length ?? 0) > 0 && (
            <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {status.runtimes!.map((rt) => (
                <div
                  key={rt.runtime}
                  className="rounded-xl border border-slate-800 bg-slate-900/50 p-4"
                >
                  <p className="text-xs uppercase tracking-wide text-slate-500">
                    {rt.runtime}
                  </p>
                  <p className="mt-1 flex items-center gap-2 text-lg font-medium">
                    <span
                      className={`h-2.5 w-2.5 rounded-full ${
                        rt.available && rt.gateway?.running
                          ? "bg-emerald-400"
                          : rt.available
                            ? "bg-amber-400"
                            : "bg-red-400"
                      }`}
                    />
                    {rt.available
                      ? rt.gateway?.running
                        ? "Gateway 运行中"
                        : "CLI 可用"
                      : "不可用"}
                  </p>
                  <p className="mt-2 text-xs text-slate-400">
                    v{rt.version || "—"}
                    {rt.gateway?.pid ? ` · PID ${rt.gateway.pid}` : ""}
                    {rt.gateway?.port ? ` · 端口 ${rt.gateway.port}` : ""}
                  </p>
                </div>
              ))}
            </section>
          )}

          <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <p className="text-xs text-slate-500">OpenClaw Gateway（兼容）</p>
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
              <p className="text-xs text-slate-500">Cron 任务（聚合）</p>
              <p className="mt-1 text-lg font-medium">{status.cron_jobs.length}</p>
              <p className="mt-2 text-xs text-red-400">
                {status.cron_errors.length} 条错误
              </p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <p className="text-xs text-slate-500">Sessions（聚合）</p>
              <p className="mt-1 text-lg font-medium">{status.sessions_count}</p>
              <p className="mt-2 text-xs text-slate-400">
                更新于 {formatTime(status.checked_at)}
              </p>
            </div>
          </section>

          {status.cron_errors.length > 0 && (
            <section>
              <div className="mb-3 flex items-center justify-between gap-3">
                <h2 className="text-sm font-medium text-red-300">Cron 错误</h2>
                {repairMsg && (
                  <p className="truncate text-xs text-slate-400" title={repairMsg}>
                    {repairMsg}
                  </p>
                )}
              </div>
              <div className="overflow-hidden rounded-xl border border-red-900/40">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-800 bg-red-950/30 text-left text-xs text-slate-400">
                      <th className="px-4 py-3">运行时</th>
                      <th className="px-4 py-3">名称</th>
                      <th className="px-4 py-3">Agent</th>
                      <th className="px-4 py-3">状态</th>
                      <th className="px-4 py-3">上次运行</th>
                      <th className="px-4 py-3 text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.cron_errors.map((j) => (
                      <tr key={j.id} className="border-t border-slate-800/80">
                        <td className="px-4 py-3 text-xs uppercase text-slate-500">
                          {j.runtime || j.source || "—"}
                        </td>
                        <td className="px-4 py-3">{j.name}</td>
                        <td className="px-4 py-3 font-mono text-xs">{j.agent_id}</td>
                        <td className="px-4 py-3">
                          <StatusBadge status={j.status || j.last_status || "error"} />
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500">
                          {j.last_run ? formatTime(j.last_run) : "—"}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            disabled={!!repairingId}
                            onClick={() => repairCron(j.id, j.name)}
                            className="rounded-md border border-amber-700/60 bg-amber-950/40 px-2.5 py-1 text-xs text-amber-100 hover:bg-amber-900/50 disabled:cursor-not-allowed disabled:opacity-50"
                            title="派单给 ops-agent 诊断并尝试修复"
                          >
                            {repairingId === j.id ? "派单中…" : "修复"}
                          </button>
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
                    <th className="px-4 py-3">运行时</th>
                    <th className="px-4 py-3">名称</th>
                    <th className="px-4 py-3">Agent</th>
                    <th className="px-4 py-3">调度</th>
                    <th className="px-4 py-3">状态</th>
                  </tr>
                </thead>
                <tbody>
                  {status.cron_jobs.map((j) => (
                    <tr key={j.id} className="border-t border-slate-800/80">
                      <td className="px-4 py-3 text-xs uppercase text-slate-500">
                        {j.runtime || j.source || "—"}
                      </td>
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
            <h2 className="mb-3 text-sm font-medium text-slate-300">告警规则</h2>
            <form
              onSubmit={saveAlertRules}
              className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/50 p-4"
            >
              <div className="flex flex-wrap items-end gap-2">
                <label className="block text-xs text-slate-500">
                  环境 profile
                  <select
                    value={alertProfile}
                    onChange={(e) => switchProfile(e.target.value)}
                    className="mt-1 block min-w-[140px] rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
                  >
                    {profileList.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </label>
                <input
                  value={newProfile}
                  onChange={(e) => setNewProfile(e.target.value)}
                  placeholder="新环境名，如 prod"
                  className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
                />
                <button
                  type="button"
                  onClick={createProfile}
                  disabled={savingAlert || !newProfile.trim()}
                  className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
                >
                  创建环境
                </button>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="flex items-center gap-2 text-sm text-slate-300">
                  <input
                    type="checkbox"
                    checked={cronEnabled}
                    onChange={(e) => setCronEnabled(e.target.checked)}
                  />
                  Cron 错误告警
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-300">
                  <input
                    type="checkbox"
                    checked={gatewayEnabled}
                    onChange={(e) => setGatewayEnabled(e.target.checked)}
                  />
                  Gateway 宕机告警
                </label>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block text-xs text-slate-500">
                  检查间隔（秒，≥60）
                  <input
                    type="number"
                    min={60}
                    value={intervalDraft}
                    onChange={(e) => setIntervalDraft(Number(e.target.value) || 60)}
                    className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
                  />
                </label>
                <label className="block text-xs text-slate-500">
                  磁盘告警阈值（%，0=关闭）
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={diskDraft}
                    onChange={(e) => setDiskDraft(Number(e.target.value) || 0)}
                    className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
                  />
                </label>
              </div>
              <label className="block text-xs text-slate-500">
                飞书 Webhook
                {alertSettings?.webhook_url_set && (
                  <span className="ml-2 text-emerald-500/80">
                    已配置 {alertSettings.webhook_url_masked}
                  </span>
                )}
                <input
                  type="url"
                  value={webhookDraft}
                  onChange={(e) => setWebhookDraft(e.target.value)}
                  placeholder="留空则不修改现有 URL"
                  className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
                />
              </label>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="submit"
                  disabled={savingAlert}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm hover:bg-indigo-500 disabled:opacity-50"
                >
                  {savingAlert ? "保存中…" : "保存规则"}
                </button>
                {alertSaveMsg && (
                  <span className="text-xs text-slate-400">{alertSaveMsg}</span>
                )}
              </div>
            </form>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-medium text-slate-300">
              告警历史（Cron / Gateway / Disk）
            </h2>
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
                      <th className="px-4 py-3">类型</th>
                      <th className="px-4 py-3">告警数</th>
                      <th className="px-4 py-3">涉及</th>
                      <th className="px-4 py-3">飞书推送</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alerts.map((a, i) => (
                      <tr key={i} className="border-t border-slate-800/80">
                        <td className="px-4 py-3 text-xs text-slate-400">
                          {a.at ? formatTime(a.at) : "—"}
                        </td>
                        <td className="px-4 py-3 text-xs uppercase text-slate-500">
                          {a.kind || "cron"}
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
                            className={`text-xs ${
                              a.sent
                                ? "text-emerald-400"
                                : a.kind
                                  ? "text-amber-400"
                                  : "text-red-400"
                            }`}
                          >
                            {a.sent ? "✓ 已发送" : "未发送/Mock"}
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
