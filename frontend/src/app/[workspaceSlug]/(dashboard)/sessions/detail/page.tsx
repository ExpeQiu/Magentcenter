import { Suspense } from "react";
import { SessionDetailView } from "@/components/sessions/session-detail-view";

export default function Page() {
  return (
    <Suspense fallback={<p className="p-6 text-sm text-slate-500">加载会话…</p>}>
      <SessionDetailView />
    </Suspense>
  );
}
