/** 静态导出用的预置工作区 slug，与 guide/workspaces.yml 对齐。 */
export const STATIC_WORKSPACE_SLUGS = ["cyber", "geely"] as const;

export function workspaceStaticParams(): { workspaceSlug: string }[] {
  return STATIC_WORKSPACE_SLUGS.map((workspaceSlug) => ({ workspaceSlug }));
}
