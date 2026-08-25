import { Suspense } from "react";
import { ProjectDetailView } from "@/components/projects/project-detail-view";

export default function Page() {
  return (
    <Suspense fallback={<p className="p-6 text-sm text-slate-500">加载项目…</p>}>
      <ProjectDetailView />
    </Suspense>
  );
}
