"use client";

import { useEffect, useState } from "react";
import { Sidebar } from "./sidebar";
import { ModalProvider } from "@/lib/context/modal-context";
import { TerminalProvider } from "@/lib/context/terminal-context";
import { CreateTaskModal } from "@/components/modals/create-task-modal";
import { api } from "@/lib/api";

export function DashboardLayout({ children }: { children: React.ReactNode }) {
  const [healthLabel, setHealthLabel] = useState("连接中...");
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    const load = () =>
      api
        .health()
        .then((h) =>
          setHealthLabel(
            `${h.mock_mode ? "Mock" : "Live"} · OpenClaw ${h.openclaw_version || "N/A"}`
          )
        )
        .catch(() => setHealthLabel("API 离线"));
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "c" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        const tag = (e.target as HTMLElement)?.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
        e.preventDefault();
        document.dispatchEvent(new CustomEvent("agentcenter:create-task"));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <ModalProvider>
      <TerminalProvider>
        <div className="flex h-svh overflow-hidden bg-slate-950">
          {/* 桌面侧栏 */}
          <div className="hidden md:flex">
            <Sidebar healthLabel={healthLabel} />
          </div>
          {/* 手机抽屉 */}
          {navOpen && (
            <div className="fixed inset-0 z-40 md:hidden">
              <button
                type="button"
                aria-label="关闭菜单"
                className="absolute inset-0 bg-black/60"
                onClick={() => setNavOpen(false)}
              />
              <div className="relative z-10 h-full w-64 max-w-[85vw] shadow-xl">
                <Sidebar
                  healthLabel={healthLabel}
                  onNavigate={() => setNavOpen(false)}
                />
              </div>
            </div>
          )}
          <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
            <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-slate-800 bg-slate-950/95 px-4 py-3 backdrop-blur md:hidden">
              <button
                type="button"
                onClick={() => setNavOpen(true)}
                className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200"
              >
                菜单
              </button>
              <span className="truncate text-sm font-medium text-slate-100">
                AgentCenter
              </span>
            </header>
            <div className="mx-auto w-full max-w-[93.6rem] px-4 py-4 md:px-6 md:py-6">
              {children}
            </div>
          </main>
        </div>
        <CreateTaskModal />
      </TerminalProvider>
    </ModalProvider>
  );
}
