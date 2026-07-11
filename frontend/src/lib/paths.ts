/** 集中路径构建，禁止硬编码路由字符串 */

const enc = (id: string) => encodeURIComponent(id);

export const DEFAULT_WORKSPACE_SLUG = "cyber";

export const paths = {
  root: (slug = DEFAULT_WORKSPACE_SLUG) => `/${slug}/tasks`,
  workspace: (slug: string) => ({
    tasks: () => `/${slug}/tasks`,
    taskDetail: (id: string) => `/${slug}/tasks/${enc(id)}`,
    projects: () => `/${slug}/projects`,
    projectDetail: (id: string) => `/${slug}/projects/${enc(id)}`,
    agents: () => `/${slug}/agents`,
    agentDetail: (id: string) => `/${slug}/agents/${enc(id)}`,
    squads: () => `/${slug}/squads`,
    autopilots: () => `/${slug}/autopilots`,
    skills: () => `/${slug}/skills`,
    system: () => `/${slug}/system`,
    sessions: () => `/${slug}/sessions`,
    sessionDetail: (id: string) => `/${slug}/sessions/${enc(id)}`,
  }),
} as const;

/** 旧版扁平路径 → 工作区路径 */
export const LEGACY_PREFIXES = [
  "tasks",
  "projects",
  "agents",
  "squads",
  "autopilots",
  "skills",
  "system",
  "sessions",
] as const;
