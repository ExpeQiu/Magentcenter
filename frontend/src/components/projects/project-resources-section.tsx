"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type {
  GithubRepoRef,
  LocalDirectoryRef,
  ProjectResourceInfo,
} from "@/lib/types";

function isGithubRef(
  ref: GithubRepoRef | LocalDirectoryRef
): ref is GithubRepoRef {
  return "url" in ref;
}

export function ProjectResourcesSection({ projectId }: { projectId: string }) {
  const [resources, setResources] = useState<ProjectResourceInfo[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [rtype, setRtype] = useState<"github_repo" | "local_directory">(
    "github_repo"
  );
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [ref, setRef] = useState("main");
  const [localPath, setLocalPath] = useState("");

  const load = () =>
    api.projectResources(projectId).then(setResources).catch(console.error);

  useEffect(() => {
    load();
  }, [projectId]);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      if (rtype === "github_repo") {
        await api.createProjectResource(projectId, {
          resource_type: "github_repo",
          label,
          ref: { url, ref },
        });
      } else {
        await api.createProjectResource(projectId, {
          resource_type: "local_directory",
          label,
          ref: { local_path: localPath, label },
        });
      }
      setShowForm(false);
      setLabel("");
      setUrl("");
      setLocalPath("");
      load();
    } catch {
      alert("添加资源失败");
    }
  };

  const remove = async (id: string) => {
    if (!confirm("删除此资源？")) return;
    await api.deleteProjectResource(projectId, id);
    load();
  };

  return (
    <section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium text-slate-300">项目资源</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="text-xs text-indigo-400 hover:underline"
        >
          + 绑定资源
        </button>
      </div>
      {showForm && (
        <form onSubmit={add} className="mb-4 space-y-2 rounded-lg border border-slate-800 p-3">
          <select
            value={rtype}
            onChange={(e) =>
              setRtype(e.target.value as "github_repo" | "local_directory")
            }
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          >
            <option value="github_repo">GitHub Repo</option>
            <option value="local_directory">本地目录</option>
          </select>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="标签"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          />
          {rtype === "github_repo" ? (
            <>
              <input
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://github.com/org/repo"
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
              />
              <input
                value={ref}
                onChange={(e) => setRef(e.target.value)}
                placeholder="分支 ref"
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
              />
            </>
          ) : (
            <input
              value={localPath}
              onChange={(e) => setLocalPath(e.target.value)}
              placeholder="/path/to/project"
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
            />
          )}
          <button type="submit" className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm">
            添加
          </button>
        </form>
      )}
      {resources.length === 0 ? (
        <p className="text-xs text-slate-500">暂无绑定资源</p>
      ) : (
        <ul className="space-y-2">
          {resources.map((r) => (
            <li
              key={r.id}
              className="flex items-start justify-between rounded-lg border border-slate-800 px-3 py-2 text-sm"
            >
              <div>
                <p className="font-medium text-slate-200">
                  {r.label || r.resource_type}
                  <span className="ml-2 text-xs text-slate-500">{r.resource_type}</span>
                </p>
                {isGithubRef(r.ref) ? (
                  <p className="mt-1 font-mono text-xs text-slate-400">
                    {r.ref.url} @ {r.ref.ref}
                  </p>
                ) : (
                  <p className="mt-1 font-mono text-xs text-slate-400">
                    {r.ref.local_path}
                  </p>
                )}
              </div>
              <button
                onClick={() => remove(r.id)}
                className="text-xs text-red-400 hover:underline"
              >
                删除
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
