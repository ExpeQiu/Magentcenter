import { WorkspaceProvider } from "@/lib/context/workspace-context";

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
