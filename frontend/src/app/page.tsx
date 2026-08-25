"use client";

import { useEffect } from "react";
import { getLastWorkspaceSlug } from "@/lib/context/workspace-context";
import { paths } from "@/lib/paths";

export default function Home() {
  useEffect(() => {
    window.location.replace(paths.root(getLastWorkspaceSlug()));
  }, []);
  return <p className="p-6 text-sm text-slate-400">正在进入工作区…</p>;
}
