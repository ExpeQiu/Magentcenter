"use client";

import { useEffect, useState } from "react";
import { Sidebar } from "./sidebar";
import { ModalProvider } from "@/lib/context/modal-context";
import { CreateTaskModal } from "@/components/modals/create-task-modal";
import { api } from "@/lib/api";

export function DashboardLayout({ children }: { children: React.ReactNode }) {
  const [healthLabel, setHealthLabel] = useState("连接中...");

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
      <div className="flex h-svh overflow-hidden bg-slate-950">
        <Sidebar healthLabel={healthLabel} />
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[93.6rem] px-6 py-6">{children}</div>
        </main>
      </div>
      <CreateTaskModal />
    </ModalProvider>
  );
}
