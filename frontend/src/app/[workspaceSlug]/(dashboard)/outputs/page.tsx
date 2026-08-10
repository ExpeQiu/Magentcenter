import { Suspense } from "react";
import { OutputsPage } from "@/components/outputs/outputs-page";

export default function Page() {
  return (
    <Suspense fallback={<p className="p-6 text-sm text-slate-500">加载输出物…</p>}>
      <OutputsPage />
    </Suspense>
  );
}
