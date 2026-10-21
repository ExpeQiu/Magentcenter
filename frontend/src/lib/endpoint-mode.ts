import type { FleetNode } from "@/lib/types";

export type EndpointMode = "cloud" | "pc" | "hardware" | "voice";

export type NavKey =
  | "super"
  | "kanban"
  | "tasks"
  | "workflow"
  | "agents"
  | "squads"
  | "autopilot"
  | "skills"
  | "fleet"
  | "system"
  | "sessions"
  | "knowledge"
  | "outputs";

export const MODE_ORDER: EndpointMode[] = ["cloud", "pc", "hardware", "voice"];

export const MODE_LABEL: Record<EndpointMode, string> = {
  cloud: "云服务器",
  pc: "本地PC",
  hardware: "智能硬件",
  voice: "语音对话",
};

export const CLOUD_TERMINAL_LABEL = "云端";

const NAV_BY_MODE: Record<EndpointMode, NavKey[]> = {
  cloud: ["super", "tasks", "fleet", "system"],
  pc: [
    "super",
    "kanban",
    "tasks",
    "workflow",
    "agents",
    "squads",
    "autopilot",
    "skills",
    "fleet",
    "system",
    "sessions",
    "knowledge",
    "outputs",
  ],
  hardware: ["super", "tasks", "agents", "fleet", "system"],
  voice: ["super", "sessions"],
};

export function isEndpointMode(value: string): value is EndpointMode {
  return value === "cloud" || value === "pc" || value === "hardware" || value === "voice";
}

/** 云端服务（8080 或 deploy_profile=cloud）打开时，类别默认是「云服务器」，绑定终端是「云端」。 */
export function defaultEndpointMode(input: { port?: string; deployProfile?: string } = {}): EndpointMode {
  if ((input.port || "") === "8080") return "cloud";
  if ((input.deployProfile || "").trim().toLowerCase() === "cloud") return "cloud";
  return "pc";
}

export function navKeysForMode(mode: EndpointMode): NavKey[] {
  return NAV_BY_MODE[mode];
}

export function allowsCreateTask(mode: EndpointMode): boolean {
  return mode !== "voice";
}

function isComputerPlatform(platform: string): boolean {
  const value = platform.trim().toLowerCase();
  return value === "darwin" || value === "win32" || value === "windows";
}

export function modeOfNode(node: Pick<FleetNode, "mode" | "self" | "platform" | "bound">): EndpointMode {
  if (node.mode === "voice") return "voice";
  if (node.self === true || node.mode === "local") return "pc";
  if (node.bound === true && isComputerPlatform(node.platform || "")) return "pc";
  return "hardware";
}

export function nodesForMode(nodes: FleetNode[], mode: EndpointMode): FleetNode[] {
  if (mode === "cloud") return [];
  return nodes
    .filter((node) => modeOfNode(node) === mode)
    .sort((a, b) => {
      if (a.online !== b.online) return a.online ? -1 : 1;
      return a.name.localeCompare(b.name, "zh");
    });
}

export function preferredDeviceId(nodes: FleetNode[], mode: EndpointMode, rememberedId: string): string {
  if (mode === "cloud") return "";
  const group = nodesForMode(nodes, mode);
  if (rememberedId && group.some((node) => node.id === rememberedId)) return rememberedId;
  if (mode === "pc") {
    const self = group.find((node) => node.self === true && node.online) || group.find((node) => node.self === true);
    if (self) return self.id;
  }
  const online = group.find((node) => node.online);
  return (online || group[0])?.id || "";
}

export function reconcileEndpoint(
  nodes: FleetNode[],
  mode: EndpointMode,
  deviceId: string
): { mode: EndpointMode; deviceId: string } {
  if (mode === "cloud") return { mode: "cloud", deviceId: "" };
  const group = nodesForMode(nodes, mode);
  if (deviceId && group.some((node) => node.id === deviceId)) return { mode, deviceId };
  if (group.length) return { mode, deviceId: preferredDeviceId(nodes, mode, "") };
  return { mode, deviceId: "" };
}

export function restoreEndpoint(
  nodes: FleetNode[],
  rememberedMode: string,
  rememberedId: string,
  fallback: EndpointMode = "pc",
  picked = false
): { mode: EndpointMode; deviceId: string } {
  const mode = isEndpointMode(rememberedMode) ? rememberedMode : "";
  const explicit = picked || (mode !== "" && mode !== "pc" && mode !== fallback);
  if (explicit && mode) {
    if (mode === "cloud") return { mode: "cloud", deviceId: "" };
    if (nodesForMode(nodes, mode).length || mode === "pc") {
      return { mode, deviceId: preferredDeviceId(nodes, mode, rememberedId) };
    }
  }
  if (fallback === "cloud") return { mode: "cloud", deviceId: "" };
  return { mode: "pc", deviceId: preferredDeviceId(nodes, "pc", rememberedId) };
}

export function routeAllowed(pathname: string, hrefs: string[]): boolean {
  return hrefs.some((href) => {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(`${href}/`);
  });
}
