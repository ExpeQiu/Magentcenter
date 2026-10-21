import type { Metadata } from "next";
import { Suspense } from "react";
import { BindPage } from "@/components/super-ai/bind-page";

export const metadata: Metadata = {
  title: "绑定终端 · AgentCenter",
  description: "用设备上的 6 位验证码绑定超级AI",
};

export default function BindRoute() {
  return (
    <Suspense fallback={null}>
      <BindPage />
    </Suspense>
  );
}
