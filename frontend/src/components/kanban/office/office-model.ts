import type { AgentInfo, KanbanTask, SquadInfo } from "@/lib/types";

export interface OfficeDriveBeat {
  agent?: string;
  to?: string;
  pose?: string;
  say?: string;
  board?: string;
  task_id?: string;
  task_status?: string;
  hold_ms?: number;
}

export interface OfficeDriveEvent {
  id: number;
  at: number;
  source: string;
  script: string;
  beats: OfficeDriveBeat[];
}

export type OfficePose = "idle" | "working" | "walking" | "talking";

export const POSE_LABEL: Record<OfficePose, string> = {
  idle: "在岗",
  working: "干活",
  walking: "移动",
  talking: "交流",
};

export const FLOW_COLUMNS = [
  { id: "triage", label: "分拣" },
  { id: "todo", label: "待办" },
  { id: "running", label: "进行" },
  { id: "done", label: "完成" },
] as const;

const DESK_SLOTS = [
  { x: 22, y: 22 },
  { x: 44, y: 22 },
  { x: 22, y: 48 },
  { x: 44, y: 48 },
  { x: 22, y: 74 },
  { x: 44, y: 74 },
];

const ACCENTS = ["#818cf8", "#34d399", "#fbbf24", "#fb7185", "#38bdf8", "#c084fc"];

export interface OfficeActor {
  id: string;
  name: string;
  emoji: string;
  runtime: string;
  accent: string;
  keys: string[];
  groupId: string;
  groupName: string;
  lead: boolean;
  alsoIn: string[];
  homeX: number;
  homeY: number;
  deskX: number;
  deskY: number;
  x: number;
  y: number;
  pose: OfficePose;
  bubble: string;
}

export interface OfficeGroup {
  id: string;
  name: string;
  x: number;
  y: number;
  w: number;
  h: number;
  color: string;
  count: number;
  leaderName: string;
}

export interface BoardNote {
  id: string;
  author: string;
  text: string;
  at: number;
}

export interface DriveBeat {
  agentId?: string;
  to?: string;
  pose?: OfficePose;
  say?: string;
  board?: string;
  taskId?: string;
  taskStatus?: string;
  holdMs?: number;
}

export interface RosterAgent {
  id: string;
  name: string;
  keys: string[];
}

export function progressOf(status: string) {
  const column = columnOf(status);
  if (column === "done") return 100;
  if (column === "running") return 62;
  if (column === "todo") return 28;
  if (column === "triage") return 12;
  return 0;
}

export function flowLabel(status: string) {
  const column = columnOf(status);
  if (column === "done") return "已完成";
  if (column === "running") return "进行中";
  if (column === "todo") return "待处理";
  if (column === "triage") return "分拣";
  return status || "其他";
}

export function columnOf(status: string): string {
  const s = (status || "").trim().toLowerCase();
  if (["done", "completed", "complete", "archived"].includes(s)) return "done";
  if (
    ["running", "doing", "in_progress", "in-progress", "progress", "review", "blocked"].includes(
      s
    )
  ) {
    return "running";
  }
  if (s === "triage") return "triage";
  if (["todo", "ready", "backlog", "open", ""].includes(s)) return "todo";
  return "other";
}

export function rosterFrom(agents: AgentInfo[]): RosterAgent[] {
  return agents.map((agent) => ({
    id: agent.id,
    name: displayName(agent),
    keys: [agent.id, agent.name, agent.identity_name]
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean),
  }));
}

export function displayName(agent: Pick<AgentInfo, "id" | "name" | "identity_name">) {
  return agent.identity_name || agent.name || agent.id;
}

export function resolveAgentId(token: string, roster: RosterAgent[]): string | null {
  const key = token.trim().toLowerCase();
  if (!key) return null;
  const exact = roster.find((agent) => agent.id.toLowerCase() === key || agent.keys.includes(key));
  if (exact) return exact.id;
  if (key.length < 2) return null;
  const fuzzy = roster.find((agent) =>
    agent.keys.some((item) => item.includes(key) || key.includes(item))
  );
  return fuzzy?.id ?? null;
}

export function tasksForActor(tasks: KanbanTask[], actor: Pick<OfficeActor, "keys">) {
  const keys = new Set(actor.keys);
  return tasks.filter((task) => keys.has((task.assignee || "").trim().toLowerCase()));
}

export function layoutActors(agents: AgentInfo[]): OfficeActor[] {
  return agents.slice(0, DESK_SLOTS.length).map((agent, index) => {
    const slot = DESK_SLOTS[index];
      const homeX = slot.x;
      const homeY = slot.y + 14;
    return {
      id: agent.id,
      name: displayName(agent),
      emoji: agent.identity_emoji || "",
      runtime: agent.runtime,
      accent: ACCENTS[index % ACCENTS.length],
      keys: [agent.id, agent.name, agent.identity_name]
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean),
      groupId: "",
      groupName: "",
      lead: false,
      alsoIn: [],
      deskX: slot.x,
      deskY: slot.y,
      homeX,
      homeY,
      x: homeX,
      y: homeY,
      pose: "idle",
      bubble: "",
    };
  });
}

const GROUP_COLORS = ["#818cf8", "#34d399", "#fbbf24", "#fb7185", "#38bdf8", "#c084fc", "#fb923c", "#2dd4bf"];

function matchAgent(token: string, agents: AgentInfo[]) {
  const key = token.trim().toLowerCase();
  if (!key) return undefined;
  return agents.find(
    (agent) =>
      agent.id.toLowerCase() === key ||
      agent.name.trim().toLowerCase() === key ||
      agent.identity_name.trim().toLowerCase() === key
  );
}

function gridShape(count: number) {
  if (count <= 1) return { cols: 1, rows: 1 };
  if (count <= 2) return { cols: 2, rows: 1 };
  if (count <= 4) return { cols: 2, rows: 2 };
  if (count <= 6) return { cols: 3, rows: 2 };
  return { cols: 4, rows: Math.ceil(count / 4) };
}

export function layoutOffice(agents: AgentInfo[], squads: SquadInfo[]) {
  const membership = new Map<string, { squadId: string; squadName: string; lead: boolean }[]>();
  const resolved = squads.map((squad) => {
    const leader = matchAgent(squad.leader, agents);
    const seats: { agent: AgentInfo; lead: boolean }[] = [];
    const seen = new Set<string>();
    for (const token of [squad.leader, ...squad.members]) {
      const agent = matchAgent(token, agents);
      if (!agent || seen.has(agent.id)) continue;
      seen.add(agent.id);
      const lead = leader?.id === agent.id;
      seats.push({ agent, lead });
      const list = membership.get(agent.id) || [];
      list.push({ squadId: squad.id, squadName: squad.name, lead });
      membership.set(agent.id, list);
    }
    return { squad, seats };
  });

  const primary = new Map<string, string>();
  for (const [agentId, list] of membership) {
    const chosen = list.find((item) => item.lead) || list[0];
    if (chosen) primary.set(agentId, chosen.squadId);
  }

  const buckets = resolved
    .map(({ squad, seats }) => ({
      id: squad.id,
      name: squad.name,
      seats: seats
        .filter((seat) => primary.get(seat.agent.id) === squad.id)
        .sort((a, b) => Number(b.lead) - Number(a.lead)),
    }))
    .filter((group) => group.seats.length > 0);

  const placed = new Set(buckets.flatMap((group) => group.seats.map((seat) => seat.agent.id)));
  const loose = agents.filter((agent) => !placed.has(agent.id));
  if (loose.length > 0) {
    buckets.push({
      id: "ungrouped",
      name: "未编组",
      seats: loose.map((agent) => ({ agent, lead: false })),
    });
  }

  const { cols, rows } = gridShape(buckets.length);
  const top = 15;
  const padX = 2;
  const padB = 2;
  const gap = 1.4;
  const zoneW = buckets.length === 0 ? 0 : (100 - padX * 2 - gap * (cols - 1)) / cols;
  const zoneH = buckets.length === 0 ? 0 : (100 - top - padB - gap * (rows - 1)) / rows;
  const groups: OfficeGroup[] = [];
  const actors: OfficeActor[] = [];

  buckets.forEach((bucket, index) => {
    const col = index % cols;
    const row = Math.floor(index / cols);
    const zone = {
      x: padX + col * (zoneW + gap),
      y: top + row * (zoneH + gap),
      w: zoneW,
      h: zoneH,
    };
    const color = GROUP_COLORS[index % GROUP_COLORS.length];
    const leader = bucket.seats.find((seat) => seat.lead);
    groups.push({
      id: bucket.id,
      name: bucket.name,
      x: zone.x,
      y: zone.y,
      w: zone.w,
      h: zone.h,
      color,
      count: bucket.seats.length,
      leaderName: leader ? displayName(leader.agent) : "",
    });
    const seatCols = bucket.seats.length <= 1 ? 1 : 2;
    const seatRows = Math.ceil(bucket.seats.length / seatCols);
    bucket.seats.forEach((seat, seatIndex) => {
      const seatCol = seatIndex % seatCols;
      const seatRow = Math.floor(seatIndex / seatCols);
      const deskX = zone.x + zone.w * (0.08 + ((seatCol + 0.5) / seatCols) * 0.84);
      const deskY = zone.y + zone.h * (0.24 + ((seatRow + 0.22) / seatRows) * 0.7);
      const homeY = Math.min(97, deskY + Math.min(8, zone.h * 0.16));
      const links = membership.get(seat.agent.id) || [];
      actors.push({
        id: seat.agent.id,
        name: displayName(seat.agent),
        emoji: seat.agent.identity_emoji || "",
        runtime: seat.agent.runtime,
        accent: color,
        keys: [seat.agent.id, seat.agent.name, seat.agent.identity_name]
          .map((item) => item.trim().toLowerCase())
          .filter(Boolean),
        groupId: bucket.id,
        groupName: bucket.name,
        lead: seat.lead,
        alsoIn: links.filter((item) => item.squadId !== bucket.id).map((item) => item.squadName),
        deskX,
        deskY,
        homeX: deskX,
        homeY,
        x: deskX,
        y: homeY,
        pose: "idle",
        bubble: "",
      });
    });
  });

  return { actors, groups };
}

export function withTaskPoses(
  actors: OfficeActor[],
  tasks: KanbanTask[],
  override: Record<string, string> = {}
): OfficeActor[] {
  return actors.map((actor) => {
    const working = tasksForActor(tasks, actor).some(
      (task) => columnOf(override[task.id] ?? task.status) === "running"
    );
    return { ...actor, pose: working ? "working" : "idle", bubble: "" };
  });
}

export function pickDuty(
  agents: AgentInfo[],
  tasks: KanbanTask[],
  manual: string[] | null
): AgentInfo[] {
  if (manual) {
    const chosen = new Set(manual);
    return agents.filter((agent) => chosen.has(agent.id)).slice(0, DESK_SLOTS.length);
  }
  const busy = new Set(
    tasks.map((task) => task.assignee.trim().toLowerCase()).filter(Boolean)
  );
  const ranked = agents.map((agent, index) => ({ agent, index }));
  ranked.sort((a, b) => {
    const score = (agent: AgentInfo) =>
      [agent.id, agent.name, agent.identity_name].some((item) =>
        busy.has(item.trim().toLowerCase())
      )
        ? 1
        : 0;
    const delta = score(b.agent) - score(a.agent);
    if (delta !== 0) return delta;
    if (a.agent.is_default !== b.agent.is_default) return a.agent.is_default ? -1 : 1;
    return a.index - b.index;
  });
  return ranked.map((item) => item.agent).slice(0, DESK_SLOTS.length);
}

export function anchorFor(to: string, actor: OfficeActor, actors: OfficeActor[]) {
  if (!to || to === "desk" || to === "work") return { x: actor.homeX, y: actor.homeY };
  if (to === "board") return { x: 74, y: 38 };
  if (to === "meet") {
    const index = Math.max(
      0,
      actors.findIndex((item) => item.id === actor.id)
    );
    const ring = [
      [62, 64],
      [72, 60],
      [82, 66],
      [78, 76],
      [64, 76],
      [58, 68],
    ];
    const [x, y] = ring[index % ring.length];
    return { x, y };
  }
  const other = actors.find((item) => item.id === to);
  if (other) {
    const slot = Math.max(
      0,
      actors.findIndex((item) => item.id === actor.id)
    );
    return {
      x: Math.min(90, other.homeX + 7 + (slot % 2) * 4),
      y: Math.min(88, other.homeY + (slot % 3) - 1),
    };
  }
  return { x: actor.homeX, y: actor.homeY };
}

function clip(text: string, max: number) {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max)}…` : clean;
}

export function buildOfficeDemo(
  actors: OfficeActor[],
  goal: string,
  tasks: KanbanTask[]
): DriveBeat[] {
  if (actors.length === 0) return [];
  const lead = actors[0];
  const title = goal.trim() || "把多 Agent 协作摊到办公室里";
  const beats: DriveBeat[] = [
    {
      agentId: lead.id,
      to: "board",
      pose: "walking",
      holdMs: 1100,
    },
    {
      agentId: lead.id,
      to: "board",
      pose: "talking",
      say: `目标：${clip(title, 28)}`,
      board: `${lead.name}：${title}`,
      holdMs: 1600,
    },
  ];

  actors.slice(1, 4).forEach((actor, index) => {
    const host = index % 2 === 0 ? lead.id : actors[index].id;
    const line = ["我先对齐输入", "我去邻座对一下", "我来收这一段"][index] || "我加入这轮";
    beats.push({ agentId: actor.id, to: host, pose: "walking", holdMs: 1100 });
    beats.push({
      agentId: actor.id,
      to: host,
      pose: "talking",
      say: line,
      board: `${actor.name}：${line}`,
      holdMs: 1400,
    });
  });

  const owned = tasks.find((task) =>
    actors.some((actor) => actor.keys.includes((task.assignee || "").trim().toLowerCase()))
  );
  if (owned) {
    beats.push({
      taskId: owned.id,
      taskStatus: "running",
      board: `任务流：${owned.title} 进入进行`,
      holdMs: 900,
    });
  }

  beats.push({
    agentId: lead.id,
    to: "meet",
    pose: "walking",
    holdMs: 1000,
  });
  beats.push({
    agentId: lead.id,
    to: "meet",
    pose: "talking",
    say: "结论写上白板，回工位",
    board: `${lead.name}：协作收束，各自回工位`,
    holdMs: 1500,
  });

  const movers = [lead, ...actors.slice(1, 4)];
  movers.forEach((actor, index) => {
    beats.push({
      agentId: actor.id,
      to: "desk",
      pose: index === 0 && owned ? "working" : "idle",
      holdMs: 650,
    });
  });
  return beats;
}

const POSES = new Set<OfficePose>(["idle", "working", "walking", "talking"]);

function asPose(value: string | undefined): OfficePose | undefined {
  if (value && POSES.has(value as OfficePose)) return value as OfficePose;
  return undefined;
}

export function parseDriveScript(
  raw: string,
  roster: RosterAgent[]
): { beats: DriveBeat[]; errors: string[] } {
  const text = raw.trim();
  if (!text) return { beats: [], errors: [] };
  if (text.startsWith("[")) {
    try {
      const data = JSON.parse(text) as unknown;
      if (!Array.isArray(data)) return { beats: [], errors: ["驱动脚本需要是数组"] };
      return beatsFromList(data as OfficeDriveBeat[], roster);
    } catch {
      return { beats: [], errors: ["驱动脚本不是合法 JSON"] };
    }
  }

  const beats: DriveBeat[] = [];
  const errors: string[] = [];
  text.split("\n").forEach((line, index) => {
    const source = line.trim();
    if (!source || source.startsWith("#")) return;
    const board = source.match(/^board\s+(.+)$/i);
    if (board) {
      beats.push({ board: board[1].trim(), holdMs: 900 });
      return;
    }
    const task = source.match(/^task\s+(\S+)\s+(\S+)$/i);
    if (task) {
      beats.push({ taskId: task[1], taskStatus: task[2], holdMs: 700 });
      return;
    }
    const visit = source.match(/^agent\s+(\S+)\s+visit\s+(\S+)\s*(.*)$/i);
    if (visit) {
      pushAgentBeat(beats, errors, roster, visit[1], visit[2], visit[3], index + 1);
      return;
    }
    const agent = source.match(/^agent\s+(\S+)\s+(desk|board|meet|work)\s*(.*)$/i);
    if (agent) {
      const verb = agent[2].toLowerCase();
      pushAgentBeat(
        beats,
        errors,
        roster,
        agent[1],
        verb === "work" ? "desk" : verb,
        agent[3],
        index + 1,
        verb === "work" ? "working" : undefined
      );
      return;
    }
    errors.push(`第 ${index + 1} 行无法识别`);
  });
  return { beats, errors };
}

function pushAgentBeat(
  beats: DriveBeat[],
  errors: string[],
  roster: RosterAgent[],
  who: string,
  to: string,
  say: string,
  line: number,
  poseOverride?: OfficePose
) {
  const agentId = resolveAgentId(who, roster);
  if (!agentId) {
    errors.push(`第 ${line} 行没有这个工位：${who}`);
    return;
  }
  let target = to;
  if (to !== "desk" && to !== "board" && to !== "meet") {
    const other = resolveAgentId(to, roster);
    if (!other) {
      errors.push(`第 ${line} 行没有拜访对象：${to}`);
      return;
    }
    target = other;
  }
  const pose: OfficePose =
    poseOverride || (target === "desk" ? "idle" : "talking");
  const spoken = say.trim();
  beats.push({
    agentId,
    to: target,
    pose: "walking",
    holdMs: 1000,
  });
  beats.push({
    agentId,
    to: target,
    pose: spoken ? "talking" : pose,
    say: spoken,
    board: spoken,
    holdMs: spoken ? 1600 : 900,
  });
}

export function beatsFromEvent(event: OfficeDriveEvent, roster: RosterAgent[]) {
  if (event.beats.length > 0) return beatsFromList(event.beats, roster);
  if (event.script.trim()) return parseDriveScript(event.script, roster);
  return { beats: [] as DriveBeat[], errors: [] as string[] };
}

function beatsFromList(
  list: Array<Partial<OfficeDriveBeat> & { agentId?: string; say?: string }>,
  roster: RosterAgent[]
): { beats: DriveBeat[]; errors: string[] } {
  const beats: DriveBeat[] = [];
  const errors: string[] = [];
  list.forEach((item, index) => {
    const token = String(item.agent || item.agentId || "").trim();
    const agentId = token ? resolveAgentId(token, roster) : undefined;
    if (token && !agentId) {
      errors.push(`第 ${index + 1} 拍没有这个工位：${token}`);
      return;
    }
    let to = String(item.to || "").trim();
    if (to && !["desk", "board", "meet", "work"].includes(to)) {
      const other = resolveAgentId(to, roster);
      if (!other) {
        errors.push(`第 ${index + 1} 拍没有拜访对象：${to}`);
        return;
      }
      to = other;
    }
    if (to === "work") to = "desk";
    beats.push({
      agentId: agentId || undefined,
      to: to || undefined,
      pose: asPose(item.pose),
      say: String(item.say || "").trim(),
      board: String(item.board || "").trim(),
      taskId: String(item.task_id || "").trim() || undefined,
      taskStatus: String(item.task_status || "").trim() || undefined,
      holdMs: Number(item.hold_ms) > 0 ? Number(item.hold_ms) : undefined,
    });
  });
  return { beats, errors };
}
