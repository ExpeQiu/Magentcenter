import type { Metadata } from "next";
import { SuperAiPage } from "@/components/super-ai/super-ai-page";

export const metadata: Metadata = {
  title: "超级AI · AgentCenter",
  description: "用语音或文字调用任务、知识库、技能与系统状态",
};

export default function Home() {
  return <SuperAiPage />;
}
