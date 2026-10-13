import { Suspense } from "react";
import { SopDetailView } from "@/components/sops/sop-detail-view";

export default function Page() {
  return (
    <Suspense fallback={<p className="p-6 text-sm text-slate-500">加载 SOP…</p>}>
      <SopDetailView />
    </Suspense>
  );
}
