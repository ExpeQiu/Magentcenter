import { WorkspaceProvider } from "@/lib/context/workspace-context";
import { workspaceStaticParams } from "@/lib/workspace-slugs";

export function generateStaticParams() {
  return workspaceStaticParams();
}

export const dynamicParams = false;

export default async function WorkspaceLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ workspaceSlug: string }>;
}) {
  const { workspaceSlug } = await params;
  return <WorkspaceProvider slug={workspaceSlug}>{children}</WorkspaceProvider>;
}
