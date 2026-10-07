# AgentCenter 架构设计

## 定位

双运行时 Agent 编排中台：同时管理 **OpenClaw** 与 **Hermes**，吸收 Multica 核心思想：

- **Agent 即队友**：聚合 `openclaw agents list` + `hermes profile list`
- **任务生命周期**：queued → running → completed/failed/cancelled（任务带 `runtime`）
- **统一运行时路由**：按 `runtime` 分发到对应 Adapter
- **实时进度**：SSE + WebSocket 推送事件
- **聚合观测**：Gateway / Cron / Sessions 双栈汇总

## 架构图

```
调用方 (HTTP/WS/脚本/控制台)
        │
        ▼
  FastAPI Backend
  ├── AgentRegistry   ← openclaw + hermes providers
  ├── TaskManager     ← 按 task.runtime 选 executor
  ├── MonitorHub      ← OpenClawMonitor + HermesMonitor
  └── Autopilot       ←（P1）按 runtime 分流 cron
        │
        ├── OpenClawAdapter  → openclaw agent --local --json
        └── HermesAdapter    → hermes chat -q --quiet --source tool
```

## 核心模块

### AgentRegistry

- 多 provider：`openclaw` / `hermes`（Mock 时各一套）
- Agent 带 `runtime` 字段；查找为 `(runtime, agent_id)`
- 60s 内存缓存

### OpenClawAdapter

- 版本门禁（最低 2026.5.5）
- 参数：`--local --json --agent <id> --session-id --message`
- 输出解析：整段 JSON 优先，NDJSON 降级

### HermesAdapter

- Profile 列表：`hermes profile list`
- 执行：`hermes [--profile X] chat -q … --quiet --source tool`
- quiet 输出解析 `session_id:` + 最终文本

### TaskManager

- SQLite 持久化任务与事件（含 `runtime` 列）
- 串行锁键：`(runtime, agent_id)`
- 全局并发上限（默认 3）

### MonitorHub

- 聚合两边 Gateway / Cron / Sessions
- `SystemStatus.runtimes[]` 为双栈面板；`gateway` 字段兼容旧 OpenClaw 视图
- Hermes cron id 前缀 `hermes:`，避免与 OpenClaw 冲突

## 事件类型

`text` | `tool_use` | `tool_result` | `status` | `error` | `result`

## 配置

见 `.env.example`：`RUNTIMES` / `DEFAULT_RUNTIME` / `HERMES_*` / `OPENCLAW_*` / `OUTPUTS_VAULT_ROOT` / `OUTPUTS_VAULT_EXTRA`。

### 输出物（Outputs）

- 控制台页 `/{workspace}/outputs`：只读索引 Obsidian `expe` 库，默认本机 iCloud `…/iCloud~md~obsidian/Documents/expe`。页面上可以改目录，空路径恢复默认，记在 `data/content_roots.json`。`OUTPUTS_VAULT_EXTRA` 可追加其他目录，以文件夹名出现在一级
- 「定义范围」从一级目录（Document / Github / openclaw / 额外根 等）逐级勾选
- 列表：全部普通文件；跳过 `.obsidian` / `.git` 等系统目录
- 预览：Markdown 渲染；其它文本原文；二进制仅展示元信息
- API：`GET /api/outputs/{status,tree,recent,file}`；路径逃逸拒绝
- 来源标签：`HermesCenter/**` → hermes，其余 → openclaw
- 与知识库（SQLite 检索）并列，不合并

### 知识库（Personal Wiki）

详见 [knowledge.md](./knowledge.md)，决策见 ADR-003。

- **三层**：L2 模式与决策 ×3.0、L3 流程与工具 ×1.2、L1 事实 ×1.0；`notes` 默认不召回。子目录对齐 Personal Wiki v1.0
- **路由**：写入和召回走同一张表；旧 `playbook` 等 kind 仍可读并映射
- **任务五步**：高风险门禁、软召回、打标、复盘、跨源查询。自动召回只对高风险
- **划界**：运行时 `MEMORY.md` / Skill 正文 / Outputs 不进中心检索
- **脱敏**：入库与注入前 redact token / webhook / `sk-` 等

### 技能（目录 + 自挖掘）

详见 [skills.md](./skills.md)。

- **正文**：仍在 OpenClaw / Hermes 技能目录，中心扫描、安装、下线
- **五段引擎**：捕获 → 提炼 → 验证 → 存储 → 检索。显式「做成技能」才提炼；任务成功只写入 `_captured`
- **调用**：只有 `verified` 注入下次任务。决策类 ×3.0，流程类 ×1.2。失败三次进 `_archive`
- **账本**：SQLite 只存触发词、状态、来源、用量；与 Wiki L3 `tools` 互相留指针

## 多端调度

云端只做协调器。设备名册来自扫描和绑定，不写死。

- 本机：控制台 `/{workspace}/fleet` 扫描协调器上的 OpenClaw / Hermes，勾选后绑定。绑定的智能体由协调器本机执行
- 握手：同一页「握手并绑定」用注册令牌和云端互相证明，把本机智能体绑定到云端，并取回其他已绑定端的智能体与能力（`openclaw.agent` / `hermes.chat` / `task.execute`）。地址留空表示这台协调器。云端若还是旧接口（没有 `/api/fleet/handshake`），则改走注册和设备列表。已写在 `data/fleet_link.json` 的地址不会被 `FLEET_CLOUD_URL` 盖回
- 其他设备：安装独立包 `fleet-edge/`（`pip install` 后运行 `fleet-edge`）。它在 NAT 后扫描本机智能体并上报。控制台里对待绑定设备勾选确认
- 侧栏按设备名切换当前终端。多端页和新建任务都跟着这台设备走
- 给智能体分配任务可以在「任务」里做。已绑定设备上的智能体会出现在新建任务的列表中，并带到对应设备
- 任意已绑定端（含云端本机）可以调用其他端上的智能体或子智能体：`POST /api/fleet/call`。带设备令牌时调用方是该终端；不带令牌时调用方是云端本机。目标必须是另一台已绑定设备上的智能体。绑定列表中的第一个是主智能体，其余按子智能体派发。目标在云端本机则由协调器执行，在其他设备则排队等该设备领取并回写结果
- `node_id=auto` 只选当前在线、且已绑定该智能体的设备。指定离线设备时任务排队，等连接器来领
- 设备地址能被云端访问时，可用 webhook（签名头 `X-Fleet-Timestamp` + `X-Fleet-Signature`，算法与飞书机器人相同）
- 令牌只存哈希。注册令牌 `FLEET_ENROLL_TOKEN`，设备令牌落在 `~/.agentcenter/<node>.token`

## 分期路线

- **Phase 1**：API 网关 + 任务引擎（OpenClaw）
- **Phase 2**：Next.js 控制台
- **Phase 3**：Squads + Autopilot + 技能目录
- **Phase 4**：双运行时 P0 — Hermes Adapter + 聚合观测 + 任务 `runtime`
- **Phase 5**：Autopilot 聚合 OpenClaw/Hermes cron；Hermes session 详情；Squads `runtime`
- **Phase 6**：Skills 双目录；Gateway/Cron 告警；Hermes Kanban 列表/创建/`run` 映射
- **Phase 7**：Kanban Swarm 图；Skills 安装分流到 Hermes；告警规则配置 UI
- **Phase 8**：Session/任务知识库检索；告警持久化；Hermes 技能下线
- **Phase 9**：哈希向量检索；告警规则落盘；Session 消息级索引
- **Phase 10**：可选 Embedding HTTP；告警多环境 profile；知识库独立页
- **Phase 11**：输出物 Tab（vault 目录/最近/预览）
- **Phase 12**：知识库内容模型（卡片蒸馏 + 任务前注入 + workspace 字段 + 划界文档）
- **Phase 13**：桌面端 Tauri 2 DMG（静态前端 + FastAPI sidecar，见 ADR-002）
- **Phase 14**：Outputs→ArtifactRef 批量建指；Embedding 批量重嵌入；告警 profile 导入导出；卡片质量评分
- **Phase 15**：多端只做扫描和绑定。给智能体的任务统一从「任务」发出
- **Phase 16**：知识库改为 Personal Wiki 三层加权召回；技能捕获 / 提炼 / 验证已按 ADR-003 落地
- **Phase 17（当前）**：首页为「超级AI」对话页。`POST /api/super-ai/turn` 统一处理文字与语音转写，只调用任务、知识库、技能、输出物、系统、多端；建任务须回复「确认」

## 超级AI 首页

- 路由 `/` 是对话页，控制台仍在 `/{workspace}/tasks`
- 意图是规则白名单，认不出只追问
- 日志键：`run_id`、`intent`、`service`、`workspace`
- ESP32 用 `FLEET_ENROLL_TOKEN` 登记为语音终端（`mode=voice`），不领任务。`POST /api/super-ai/device/turn` 对话；确认后云端调度执行，设备用 `GET /api/super-ai/device/tasks/{id}` 收回结果。固件在 `firmware/esp32/super_ai/`
