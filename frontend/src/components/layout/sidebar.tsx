"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import { useTerminal } from "@/lib/context/terminal-context";
import { useModal } from "@/lib/context/modal-context";

interface SidebarProps {
  healthLabel: string;
}

export function Sidebar({ healthLabel }: SidebarProps) {
  const pathname = usePathname();
  const wp = useWorkspacePaths();
  const { openCreateTask } = useModal();
  const { nodes, selected, select } = useTerminal();
  const [open, setOpen] = useState(false);

  const NAV = [
    { href: wp.tasks(), label: "任务", icon: "📋" },
    { href: wp.projects(), label: "项目", icon: "📁" },
    { href: wp.agents(), label: "Agents", icon: "🤖" },
    { href: wp.squads(), label: "小队", icon: "👥" },
    { href: wp.autopilots(), label: "Autopilot", icon: "⏱" },
    { href: wp.skills(), label: "技能", icon: "🛠" },
    { href: wp.kanban(), label: "Kanban", icon: "📌" },
    { href: wp.fleet(), label: "多端", icon: "🖥" },
    { href: wp.system(), label: "系统", icon: "📡" },
    { href: wp.sessions(), label: "Sessions", icon: "💬" },
    { href: wp.knowledge(), label: "知识库", icon: "📚" },
    { href: wp.outputs(), label: "输出物", icon: "📄" },
  ];

  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-slate-800 bg-slate-950">
      <div className="relative border-b border-slate-800 p-3">
        <button
          onClick={() => setOpen(!open)}
          className="flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left hover:bg-slate-800/60"
        >
          <div>
            <p className="text-xs text-slate-500">终端</p>
            <p className="truncate text-sm font-semibold">{selected?.name || "未选择"}</p>
          </div>
          <span className="text-slate-500">{open ? "▴" : "▾"}</span>
        </button>
        {open && (
          <div className="absolute left-3 right-3 top-full z-20 mt-1 max-h-80 overflow-y-auto rounded-lg border border-slate-700 bg-slate-900 py-1 shadow-xl">
            {nodes.length === 0 ? (
              <p className="px-3 py-2 text-sm text-slate-500">还没有设备</p>
            ) : (
              nodes.map((node) => (
                <button
                  key={node.id}
                  type="button"
                  onClick={() => {
                    select(node.id);
                    setOpen(false);
                  }}
                  className={`block w-full px-3 py-2 text-left text-sm ${
                    node.id === selected?.id
                      ? "bg-indigo-500/15 text-indigo-200"
                      : "text-slate-300 hover:bg-slate-800"
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
        )}
      </div>

      <nav className="flex-1 space-y-0.5 p-3">
        {NAV.map((item) => {
          const active =
            pathname === item.href || pathname.startsWith(item.href + "/");
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
        <button
          onClick={() => openCreateTask()}
          className="w-full rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium hover:bg-indigo-500"
        >
          + 新建任务
        </button>
        <p className="px-1 text-xs text-slate-500">{healthLabel}</p>
      </div>
    </aside>
  );
}
