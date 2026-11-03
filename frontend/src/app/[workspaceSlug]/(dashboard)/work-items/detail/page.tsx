import { Suspense } from "react";
import { WorkItemDetail } from "@/components/work-items/work-item-detail";

export default function Page() {
  return (
    <Suspense fallback={<p className="text-sm text-slate-500">加载中…</p>}>
      <WorkItemDetail />
    </Suspense>
  );
}
