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

见 `.env.example`：`RUNTIMES` / `DEFAULT_RUNTIME` / `HERMES_*` / `OPENCLAW_*` / `OUTPUTS_VAULT_ROOT`。

### 输出物（Outputs）

- 控制台页 `/{workspace}/outputs`：只读索引 Obsidian `expe` 库（默认 `…/Documents/expe`）；「定义范围」从一级目录（Document / Github / openclaw 等）逐级勾选
- 列表：全部普通文件；跳过 `.obsidian` / `.git` 等系统目录
- 预览：Markdown 渲染；其它文本原文；二进制仅展示元信息
- API：`GET /api/outputs/{status,tree,recent,file}`；路径逃逸拒绝
- 来源标签：`HermesCenter/**` → hermes，其余 → openclaw
- 与知识库（SQLite 检索）并列，不合并

### 知识库（卡片内容模型）

详见 [knowledge.md](./knowledge.md)。

- **真源种类**：`playbook` / `precedent` / `incident` / `artifact_ref` / `shared_fact`（`archive` 仅手工归档，默认不检索）
- **划界**：运行时 `MEMORY.md` / Skills / Outputs 不进中心检索主路径；中心库做跨栈机构记忆
- **闭环**：任务完成 → 蒸馏卡片；任务创建前 → Top-K 注入 `system_prompt`（`KNOWLEDGE_INJECT_*`）
- **字段**：`kind` / `workspace_id` / `tags_json` / `payload_json` + hybrid 检索
- **脱敏**：入库与注入前 redact token / webhook / `sk-` 等

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
- **Phase 12（当前）**：知识库内容模型（卡片蒸馏 + 任务前注入 + workspace 字段 + 划界文档）
- **Phase 13（下一步）**：Outputs→ArtifactRef 批量建指；Embedding 批量重嵌入；告警 profile 导入导出；卡片质量评分
