"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace, useWorkspacePaths } from "@/lib/context/workspace-context";
import { useModal } from "@/lib/context/modal-context";
import { paths } from "@/lib/paths";
import type { WorkspaceInfo } from "@/lib/types";

interface SidebarProps {
  healthLabel: string;
}

export function Sidebar({ healthLabel }: SidebarProps) {
  const pathname = usePathname();
  const wp = useWorkspacePaths();
  const { slug } = useWorkspace();
  const { openCreateTask } = useModal();
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [wsOpen, setWsOpen] = useState(false);

  useEffect(() => {
    api.workspaces().then(setWorkspaces).catch(console.error);
  }, []);

  const current = workspaces.find((w) => w.slug === slug);

  const NAV = [
    { href: wp.tasks(), label: "任务", icon: "📋" },
    { href: wp.projects(), label: "项目", icon: "📁" },
    { href: wp.agents(), label: "Agents", icon: "🤖" },
    { href: wp.squads(), label: "小队", icon: "👥" },
    { href: wp.autopilots(), label: "Autopilot", icon: "⏱" },
    { href: wp.skills(), label: "技能", icon: "🛠" },
    { href: wp.system(), label: "系统", icon: "📡" },
    { href: wp.sessions(), label: "Sessions", icon: "💬" },
  ];

  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-slate-800 bg-slate-950">
      <div className="relative border-b border-slate-800 p-3">
        <button
          onClick={() => setWsOpen(!wsOpen)}
          className="flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left hover:bg-slate-800/60"
        >
          <div>
            <p className="text-xs text-slate-500">工作区</p>
            <p className="text-sm font-semibold">{current?.name || slug}</p>
          </div>
          <span className="text-slate-500">{wsOpen ? "▴" : "▾"}</span>
        </button>
        {wsOpen && (
          <div className="absolute left-3 right-3 top-full z-20 mt-1 rounded-lg border border-slate-700 bg-slate-900 py-1 shadow-xl">
            {workspaces.map((w) => (
              <Link
                key={w.id}
                href={paths.workspace(w.slug).tasks()}
                onClick={() => setWsOpen(false)}
                className={`block px-3 py-2 text-sm ${
                  w.slug === slug
                    ? "bg-indigo-500/15 text-indigo-200"
                    : "text-slate-300 hover:bg-slate-800"
                }`}
              >
                {w.name}
                <span className="ml-2 text-xs text-slate-500">/{w.slug}</span>
              </Link>
            ))}
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
