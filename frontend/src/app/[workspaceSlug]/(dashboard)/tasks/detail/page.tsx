import { Suspense } from "react";
import { TaskDetailView } from "@/components/tasks/task-detail-view";

export default function Page() {
  return (
    <Suspense fallback={<p className="p-6 text-sm text-slate-500">加载任务…</p>}>
      <TaskDetailView />
    </Suspense>
  );
}
