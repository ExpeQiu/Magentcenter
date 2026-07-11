"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api } from "@/lib/api";
import { DEFAULT_WORKSPACE_SLUG, paths } from "@/lib/paths";
import type { WorkspaceInfo } from "@/lib/types";

interface WorkspaceContextValue {
  slug: string;
  workspace: WorkspaceInfo | null;
  workspaceId: string;
  loading: boolean;
  refresh: () => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({
  slug,
  children,
}: {
  slug: string;
  children: ReactNode;
}) {
  const [workspace, setWorkspace] = useState<WorkspaceInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    api
      .workspaceBySlug(slug)
      .then(setWorkspace)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [slug]);

  useEffect(() => {
    setLoading(true);
    refresh();
    document.cookie = `last_workspace_slug=${encodeURIComponent(slug)}; path=/; max-age=31536000; SameSite=Lax`;
  }, [slug, refresh]);

  return (
    <WorkspaceContext.Provider
      value={{
        slug,
        workspace,
        workspaceId: workspace?.id || "",
        loading,
        refresh,
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used within WorkspaceProvider");
  return ctx;
}

export function useWorkspacePaths() {
  const { slug } = useWorkspace();
  return paths.workspace(slug);
}

export function getLastWorkspaceSlug(): string {
  if (typeof document === "undefined") return DEFAULT_WORKSPACE_SLUG;
  const match = document.cookie.match(/(?:^|;\s*)last_workspace_slug=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : DEFAULT_WORKSPACE_SLUG;
}
