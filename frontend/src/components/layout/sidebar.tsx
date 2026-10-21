"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useWorkspace } from "@/lib/context/workspace-context";
import { useTerminal } from "@/lib/context/terminal-context";
import { useModal } from "@/lib/context/modal-context";
import { paths } from "@/lib/paths";
import {
  CLOUD_TERMINAL_LABEL,
  MODE_LABEL,
  MODE_ORDER,
  allowsCreateTask,
  navKeysForMode,
  nodesForMode,
  routeAllowed,
  type NavKey,
} from "@/lib/endpoint-mode";

interface SidebarProps {
  healthLabel: string;
}

export function Sidebar({ healthLabel }: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { slug } = useWorkspace();
  const { openCreateTask } = useModal();
  const { nodes, selected, mode, ready, select, selectMode } = useTerminal();
  const [open, setOpen] = useState(false);

  const nav = useMemo(() => {
    const wp = paths.workspace(slug);
    const catalog: Record<NavKey, { href: string; label: string; icon: string }> = {
      super: { href: "/", label: "超级AI", icon: "✦" },
      kanban: { href: wp.kanban(), label: "办公室", icon: "🏢" },
      tasks: { href: wp.tasks(), label: "任务", icon: "📋" },
      workflow: { href: wp.projects(), label: "workflow", icon: "🔁" },
      agents: { href: wp.agents(), label: "Agents", icon: "🤖" },
      squads: { href: wp.squads(), label: "小队", icon: "👥" },
      autopilot: { href: wp.autopilots(), label: "Autopilot", icon: "⏱" },
      skills: { href: wp.skills(), label: "技能", icon: "🛠" },
      fleet: { href: wp.fleet(), label: "多端", icon: "🖥" },
      system: { href: wp.system(), label: "系统", icon: "📡" },
      sessions: { href: wp.sessions(), label: "Sessions", icon: "💬" },
      knowledge: { href: wp.knowledge(), label: "知识库", icon: "📚" },
      outputs: { href: wp.outputs(), label: "输出物", icon: "📄" },
    };
    return navKeysForMode(mode).map((key) => catalog[key]);
  }, [slug, mode]);
  const home = nav[0]?.href || "/";
  const allowed = nav.map((item) => item.href).join("\n");

  useEffect(() => {
    if (!ready || mode === "pc") return;
    const hrefs = allowed.split("\n");
    if (routeAllowed(pathname, hrefs)) return;
    if (home === pathname) return;
    router.push(home);
  }, [ready, mode, pathname, home, allowed, router]);

  const title = mode === "cloud" ? CLOUD_TERMINAL_LABEL : selected?.name || "未选择";

  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-slate-800 bg-slate-950">
      <div className="relative border-b border-slate-800 p-3">
        <button
          onClick={() => setOpen(!open)}
          className="flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left hover:bg-slate-800/60"
        >
          <div className="min-w-0">
            <p className="text-xs text-slate-500">{MODE_LABEL[mode]}</p>
            <p className="truncate text-sm font-semibold">{title}</p>
          </div>
          <span className="text-slate-500">{open ? "▴" : "▾"}</span>
        </button>
        {open && (
          <div className="absolute left-3 right-3 top-full z-20 mt-1 max-h-80 overflow-y-auto rounded-lg border border-slate-700 bg-slate-900 py-1 shadow-xl">
            {MODE_ORDER.map((item) => {
              const group = nodesForMode(nodes, item);
              const active = item === mode;
              return (
                <div key={item} className="border-b border-slate-800 last:border-b-0">
                  <button
                    type="button"
                    onClick={() => {
                      selectMode(item);
                      setOpen(false);
                    }}
                    className={`block w-full px-3 py-2 text-left text-sm ${
                      active ? "bg-indigo-500/15 text-indigo-200" : "text-slate-200 hover:bg-slate-800"
                    }`}
                  >
                    {MODE_LABEL[item]}
                  </button>
                  {item === "cloud" ? (
                    <button
                      type="button"
                      onClick={() => {
                        selectMode("cloud");
                        setOpen(false);
                      }}
                      className={`block w-full px-3 py-1.5 text-left text-sm ${
                        active ? "text-indigo-200" : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                      }`}
                    >
                      {CLOUD_TERMINAL_LABEL}
                      <span className="ml-2 text-xs text-slate-500">已绑定</span>
                    </button>
                  ) : group.length === 0 ? (
                    <p className="px-3 pb-2 text-xs text-slate-500">还没有设备</p>
                  ) : (
                    group.map((node) => (
                      <button
                        key={node.id}
                        type="button"
                        onClick={() => {
                          select(node.id);
                          setOpen(false);
                        }}
                        className={`block w-full px-3 py-1.5 text-left text-sm ${
                          node.id === selected?.id && active
                            ? "text-indigo-200"
                            : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                        }`}
                      >
                        {node.name}
                        <span className="ml-2 text-xs text-slate-500">
                          {node.online ? "在线" : "离线"}
                          {node.bound ? "" : " · 待绑定"}
                        </span>
                      </button>
                    ))
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <nav className="flex-1 space-y-0.5 p-3">
        {nav.map((item) => {
          const active =
            item.href === "/"
              ? pathname === "/"
              : pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition ${
                active
                  ? "bg-indigo-500/15 text-indigo-200"
                  : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
              }`}
            >
              <span>{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="space-y-2 border-t border-slate-800 p-3">
        {allowsCreateTask(mode) && (
          <button
            onClick={() => openCreateTask()}
            className="w-full rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium hover:bg-indigo-500"
          >
            + 新建任务
          </button>
        )}
        <p className="px-1 text-xs text-slate-500">{healthLabel}</p>
      </div>
    </aside>
  );
}
