# AgentCenter

OpenClaw / Hermes 双运行时 Agent 编排中台。参考 Multica「Agent 即队友、任务生命周期、统一运行时」理念，提供 REST API + SSE/WebSocket 实时事件流。

## 快速开始

```bash
cp .env.example .env
# 开发模式（无需 OpenClaw）
echo "AI_MOCK_MODE=true" >> .env

# 在本地终端（iTerm/Terminal）执行，不要依赖 Cursor 内置浏览器
./scripts/start-all.sh
./scripts/status.sh
```

**访问地址（请用系统浏览器 Safari/Chrome 打开）：**
- 控制台：http://127.0.0.1:3013
- API：http://127.0.0.1:8013/api/health

> Cursor 内置浏览器可能无法访问本机 localhost，出现 `ERR_CONNECTION_REFUSED`，请改用系统浏览器。

## 主要 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/agents` | 列出 Agent（含 runtime；可 `?runtime=`） |
| POST | `/api/tasks` | 创建并执行任务（body 可带 `runtime`） |
| GET | `/api/system-status` | 双栈 Gateway / Cron / Sessions |
| GET | `/api/skills` | 双目录技能（`?runtime=`） |
| POST | `/api/skills/install` | 安装分流（`runtime=openclaw|hermes`） |
| GET/POST | `/api/kanban/tasks` | Hermes Kanban 列表/创建 |
| POST | `/api/kanban/tasks/{id}/run` | Kanban → Hermes 任务 |
| POST/GET | `/api/kanban/swarm` | Swarm 图创建 / 按 root 查询 |
| GET/PATCH | `/api/settings/alert` | 告警规则多环境（`alert_profiles.json`） |
| GET/POST | `/api/settings/alert/profiles` | 告警环境列表 / 创建 / 激活 |
| GET | `/api/knowledge/search` | 卡片检索（`kind`/`workspace_id`/`mode`；默认不含 archive） |
| GET | `/api/knowledge/status` | 向量 provider + 支持的 kind |
| GET | `/api/knowledge/inject-preview` | 任务前注入块预览 |
| POST | `/api/knowledge/entries` | 创建 shared_fact 等卡片 |
| POST | `/api/knowledge/artifact-refs` | 产物指针 |
| POST | `/api/knowledge/backfill` | 从任务表蒸馏卡片 |
| POST | `/api/knowledge/mine-vault` | 从 Obsidian openclaw 等目录挖掘知识卡片 |
| POST | `/api/knowledge/index-session/{id}` | Session 消息写入 archive |
| GET | `/api/outputs/status` | 输出物 vault 可读状态 |
| GET | `/api/outputs/tree` | 输出物单层目录 |
| GET | `/api/outputs/recent` | 最近 Markdown 产出 |
| GET | `/api/outputs/file` | 读取输出物正文 |
| POST | `/api/skills/{id}/archive` | 技能下线（`runtime=openclaw|hermes`） |
| GET | `/api/tasks/{id}` | 任务详情 |
| GET | `/api/tasks/{id}/stream` | SSE 事件流 |
| WS | `/ws/tasks/{id}` | WebSocket 事件流 |
| GET | `/api/fleet/nodes` | 已上报设备、绑定的智能体、在线状态 |
| GET | `/api/fleet/scan` | 扫描协调器本机的 OpenClaw / Hermes |
| POST | `/api/fleet/bind` | 把勾选的智能体绑定到设备 |
| DELETE | `/api/fleet/nodes/{id}` | 解除绑定 |
| POST | `/api/fleet/enroll` | 设备上报本机扫描结果并领取令牌 |
| POST | `/api/fleet/heartbeat` | 插件心跳（`X-Node-Token`） |
| POST | `/api/fleet/claim` | 插件领取一条任务 |
| POST | `/api/fleet/tasks/{id}/finish` | 设备回报结果 |

## 配置

见 [.env.example](.env.example)。关键项：

- `RUNTIMES=openclaw,hermes` — 启用的运行时
- `DEFAULT_RUNTIME=openclaw` — 未指定 runtime 时的默认值
- `AI_MOCK_MODE=true` — 跳过真实 CLI 调用
- `EMBEDDING_PROVIDER=hash|openai|http` — 知识库向量（缺省 hash）
- `KNOWLEDGE_INJECT_ENABLED` / `KNOWLEDGE_INJECT_TOP_K` — 任务前按层加权召回
- 知识库见 [guide/knowledge.md](guide/knowledge.md)，技能自挖掘见 [guide/skills.md](guide/skills.md)
- `ALERT_PROFILE=default` — 告警规则环境
- `OPENCLAW_*` / `HERMES_*` — 各栈可执行文件与超时
- `OUTPUTS_VAULT_ROOT` — Obsidian expe 库根（控制台「输出物」范围选择起点）
- `OUTPUTS_VAULT_EXTRA` — 额外只读根（逗号分隔绝对路径，以文件夹名出现在一级目录）

## 多端调度

云端跑协调器。打开 `/{工作区}/fleet`，点「握手并绑定」把本机智能体交给云端，并看其他端已经绑定的智能体和能力。地址留空就是这台协调器。也可以「扫描本机」后手动勾选。家里的机器在 NAT 后面，每台跑连接器：它扫描自己的智能体，握手绑定后再领任务。给智能体分配任务在「任务」页，不在多端页。

云端 `.env`：

```bash
HOST=0.0.0.0
FLEET_ENROLL_TOKEN=换成一长串随机串
```

其他设备安装独立包 [fleet-edge](fleet-edge/README.md)（只含连接器，不需要整个仓库）：

```bash
pip install ./fleet-edge
FLEET_ENROLL_TOKEN=与云端相同 \
AGENTCENTER_URL=http://云端:8013 \
fleet-edge
```

在本仓库里也可以 `./scripts/fleet-edge.sh`，它转调同一个包。

云端协调器读不到本机 iCloud。`./scripts/sync-waytoai.sh` 把 `~/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI` 同步到服务器 `/opt/agentcenter/WaytoAI`，并把知识库、技能目录指到其中的 `personalwiki` 和 `skills`。`./scripts/sync-waytoai.sh --install` 之后每 15 分钟同步一次。日志在 `logs/sync-waytoai.log`。依赖目录和构建产物不会上传。

设备标识默认用主机名。有公网地址时加 `--mode webhook --webhook-url http://设备:8766/fleet`，云端按飞书同类的 HMAC 签名推送。日志在 `~/.agentcenter/logs/fleet-edge.log`。`FLEET_MOCK=1` 只验证领取，不调用本机 CLI。绑定之后，在「任务」里选择该设备上的智能体即可分配。CLI 仍可用 `./scripts/ac tasks run <agent> "ping" --runtime hermes --node <设备>`。

## CLI

```bash
./scripts/ac health
./scripts/ac agents list
./scripts/ac tasks run coder "写一个 hello world" --wait
./scripts/ac tasks run default "ping" --runtime hermes --wait
./scripts/ac tasks list --status running
./scripts/ac squads list
./scripts/ac autopilots list
```

全局选项：`--base-url` / 环境变量 `AGENTCENTER_URL`，`--json` 原始输出，`-v` 调试日志。

## 开机自启（macOS）

项目在外置盘（如 `/Volumes/Lexar`）时，使用**登录项 + 看门狗**（launchd 无法访问外置盘）：

```bash
./scripts/install-daemon.sh   # 安装登录自启，崩溃自动重启
./scripts/status.sh           # 查看运行状态
./scripts/uninstall-daemon.sh # 卸载
```

登录后自动启动，看门狗每 60 秒检查服务健康并自动恢复。

## 生命周期脚本

- `./scripts/start-all.sh` — 一键启动后端+前端（临时，不持久）
- `./scripts/start.sh` — 启动 API 服务
- `./scripts/start-frontend.sh` — 启动 Next.js 控制台（端口 3013）
- `./scripts/stop.sh` — 停止后端+前端
- `./scripts/status.sh` — 检查服务状态
- `./scripts/verify.sh` — 冒烟验证
- `./scripts/package-dmg.sh` — 打包 macOS DMG（Tauri 2；输出 `dist/AgentCenter_*.dmg`）

## 桌面安装包（macOS / Tauri 2）

```bash
./scripts/package-dmg.sh
```

打开生成的 `dist/AgentCenter_*.dmg`，把 **AgentCenter** 拖进「应用程序」。首次打开若被拦截：右键图标 → 打开。

打包形态：

- 原生窗口；前端是 Next 静态页，运行时无 Node
- FastAPI sidecar 提供 API 与页面；关掉窗口会停掉 API
- 密钥不进包；安装后读 `~/Library/Application Support/AgentCenter/.env`（没有则从 `.env.example` 复制）

数据在 `~/Library/Application Support/AgentCenter/`，日志在 `~/Library/Logs/AgentCenter/`。打包日志：`logs/package-dmg.log`。

## Phase 3 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/squads` | 列出预置小队 |
| POST | `/api/squads/tasks` | 向小队 leader 分配任务 |
| GET | `/api/skills` | 扫描 OpenClaw 技能目录 |
| GET/POST | `/api/autopilots` | 定时任务管理 |
| POST | `/api/cron/{id}/repair` | 派单 ops-agent 修复异常 Cron |

## 架构

详见 [guide/architecture.md](guide/architecture.md)
