# AgentCenter 架构设计

## 定位

云端是协调器，本机智能体仍由 OpenClaw 或 Hermes 执行。

- **超级AI**：首页把一句话收成白名单意图，再调用已有服务。认不出就追问。
- **任务**：`queued` → `running` → `completed` / `failed` / `cancelled`，带 `runtime`。进度走 SSE 与 WebSocket。
- **队友**：聚合 `openclaw agents list` 与 `hermes profile list`，按 `(runtime, agent_id)` 查找。
- **多端**：连接器上报并领取任务；语音终端只对话，不领任务。
- **记忆与能力**：知识库回答「知道什么」，技能回答「会做什么」，输出物是只读文件索引。三者不合并。
- **观测**：Gateway / Cron / Sessions 双栈汇总。

## 架构图

可视化见 [2026-10-07-skota-M-AgentCenter系统架构.html](./2026-10-07-skota-M-AgentCenter系统架构.html)。

```
超级AI 网页 ── POST /api/super-ai/turn ──┐
ESP32 ── X-Device-Token ── /device/* ────┤
                                         ▼
                                   意图白名单
                                         │
         ┌──────────┬──────────┬─────────┼──────────┐
         ▼          ▼          ▼         ▼          ▼
    TaskManager   知识库     技能目录   输出物    系统 / 名册

控制台与 CLI 直接调上面这些服务，不经过意图白名单。

TaskManager
  ├── 本机：OpenClawAdapter / HermesAdapter
  └── 其他设备：排队，等 fleet-edge 领取并回写

fleet-edge（plugin / webhook）
  扫描本机智能体 → enroll → 控制台确认绑定 → claim / finish
```

## 边界

| 数据 | 放哪 | 不放哪 |
|------|------|--------|
| 任务、事件、设备名册、知识卡片、技能账本 | SQLite `data/agentcenter.db` | — |
| 技能正文 | OpenClaw / Hermes 的 `SKILL.md` | 不复制进知识库 |
| 输出物正文 | Obsidian 等只读目录 | 不进中心检索 |
| 设备令牌 | 只存哈希；明文在连接器家目录或板子上 | 不进日志 |
| 控制台改过的目录 | `data/content_roots.json` | 启动时不用 `.env` 盖回 |
| 多端云端地址 | `data/fleet_link.json` | 已有地址不用 `FLEET_CLOUD_URL` 盖回 |

工作区预置在 `guide/workspaces.yml`，默认 slug 是 `cyber`。

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
- 令牌只存哈希。注册令牌 `FLEET_ENROLL_TOKEN`。连接器令牌落在 `~/.agentcenter/<node>.token`，请求头 `X-Node-Token`。语音终端用另一套头 `X-Device-Token`，见下文「超级AI」
- 名册模式：`local`（协调器本机）、`plugin`（NAT 后领取）、`webhook`（云端推送）、`voice`（只对话）

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

## 超级AI

路由 `/` 是对话页。`POST /api/super-ai/turn` 与设备上的 `/device/turn` 走同一条 `handle_turn`。控制台仍在 `/{workspace}/tasks`。

意图是规则，不是模型分类。空话、帮助、取消、打开页面、建任务、列任务、查知识、列技能、最近产出、系统、设备，各有固定说法。对不上返回 `unknown`，并说明可以问什么。

建任务时选默认智能体，没有默认就用列表第一台。回复里带 `pending`（动作、原文、智能体、runtime）。下一句是「确认」「执行」「做吧」或「把它做了」才 `create_task`。取消类说法丢掉确认单。工作区 slug 非法时落到 `cyber`。

网页把最近 20 条对话放在 `sessionStorage`。回复若带 `href`，页面上可点进控制台。按住说话依赖浏览器语音识别。Mock 模式，或当前浏览器不能识别时，松手改发固定一句「有哪些进行中的任务」。

日志：`super_ai turn run_id=… intent=… service=… workspace=… task_id=… elapsed_ms=…`。失败打异常栈，对用户只说这项服务暂时不可用。

### 在场终端

`device_channel` 把只对话、不领任务的端收成 `mode=voice`：不扫描智能体，`bound=0`。标识若已被连接器占用，注册失败。`platform=esp32` 是语音固件，`platform=desktop` 是桌面小牛。

| 步骤 | 接口 | 头 |
|------|------|----|
| 用 `FLEET_ENROLL_TOKEN` 换设备令牌 | `POST /api/super-ai/device/enroll` | — |
| 说一句话 | `POST /api/super-ai/device/turn` | `X-Device-Token` |
| 取回播报 | `GET /api/super-ai/device/tasks/{id}` | 同上 |

`channel=voice`（默认）把回复截到约 480 字。`channel=desktop` 放到约 2000 字，给悬浮气泡。任务未结束时只报「仍在排队 / 执行中」；结束后播输出、错误或「已取消」。固件每 2 秒轮询，最多约 2 分钟，然后提示稍后再问进度。心跳沿用多端的在线判定，所以这些终端也会出现在设备列表里，但不会 `claim`。桌面小牛只把管家场景转到这里，行情和提醒留在本机。

### 信息链

跨设备的经过记在 `chain_events`，用 `GET /api/chain?task_id=` 按时间读出。登记、每一轮超级AI对话、调用方、派发、webhook 推送结果、领取、执行结束、设备取回最终结果，各是一行。确认建任务时，会把同一设备上一条「建任务」对话补上同一个 `task_id`。正文会脱敏并截断。令牌不入库。心跳只更新名册的 `last_seen`，不逐条进信息链。日志键：`chain kind=… run_id=… task_id=… actor=… target=… intent=… status=…`。
