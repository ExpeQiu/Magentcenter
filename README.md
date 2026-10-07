# AgentCenter

OpenClaw 与 Hermes 的编排中台。云端协调器负责任务、知识库、技能、输出物和设备名册；各台机器上的智能体仍在本机执行。

首页是「超级AI」：一句话只落到白名单服务（任务、知识库、技能、输出物、系统、多端）。建任务先复述，回复「确认」后才执行。控制台仍在工作区路径下，默认工作区是 `cyber`。

## 从哪进

| 入口 | 地址 | 做什么 |
|------|------|--------|
| 超级AI | http://127.0.0.1:3013 | 文字或按住说话。Mock 模式或浏览器不能识别时，松手改发「有哪些进行中的任务」 |
| 控制台 | http://127.0.0.1:3013/cyber/tasks | 任务、项目、Agents、小队、Autopilot、技能、Kanban、多端、系统、Sessions、知识库、输出物 |
| API | http://127.0.0.1:8013/api/health | 健康检查；`mock_mode` 表示是否跳过真实 CLI |

侧栏顶部按设备名切换当前终端。多端页和新建任务都跟着这台设备走。旧的 `/tasks` 等扁平路径会转到上次使用的工作区。

请用系统浏览器打开。Cursor 内置浏览器访问本机地址时，可能出现 `ERR_CONNECTION_REFUSED`。

## 快速开始

```bash
cp .env.example .env
# 开发时跳过真实 CLI
# AI_MOCK_MODE=true

./scripts/start-all.sh
./scripts/status.sh
```

## 两套设备，不要混用

| | 连接器 `fleet-edge` | 语音终端（ESP32） |
|--|---------------------|-------------------|
| 装在哪 | 跑 OpenClaw 或 Hermes 的机器 | 只说话、不跑智能体的板子 |
| 注册 | `POST /api/fleet/enroll`，须扫到智能体 | `POST /api/super-ai/device/enroll` |
| 名册模式 | `plugin` 或 `webhook` | `voice`，不领任务 |
| 之后做什么 | 心跳、领取任务、在本机执行，也可调用其他端的智能体 | `POST /api/super-ai/device/turn`；确认后的任务由云端调度，设备轮询结果 |
| 令牌 | `X-Node-Token`，文件在 `~/.agentcenter/<节点>.token` | `X-Device-Token`，固件存在板子上 |

两边共用 `FLEET_ENROLL_TOKEN`。令牌只存哈希。语音终端的设备标识若已被连接器占用，登记会被拒绝。桌面小牛走同一条在场通道：登记时 `platform=desktop`，对话带 `channel=desktop`，不领任务。

连接器说明见 [fleet-edge/README.md](fleet-edge/README.md)。固件在 `firmware/esp32/super_ai/`，串口一行文字即发送；麦克风接在发送之前即可。

## 超级AI 会接住的话

认不出就追问，不会猜着去调接口。写操作只有「建任务」，且必须先确认。

| 说法 | 调用 |
|------|------|
| 进行中的任务、任务列表 | 当前工作区任务 |
| 新建任务：… / 帮我做… | 复述默认智能体和内容，等「确认」 |
| 确认 / 执行 / 做吧 | 真正创建任务 |
| 取消 / 算了 | 丢掉确认单 |
| 什么是… / 查一下… | 知识库，最多 3 条 |
| 有哪些技能 | 未下线技能，最多 6 条 |
| 最近产出 | 输出物最近文件 |
| 系统是否正常 | 双运行时是否可用、会话数、定时异常数 |
| 哪台设备在线 | 当前工作区可见设备 |
| 打开任务台 / 知识库 / 技能 / 输出物 / 多端 / 系统 | 返回站内链接 |

工作区缺省 `cyber`。日志键是 `run_id`、`intent`、`service`、`workspace`。

## 多端调度

云端只做协调器，设备名册来自扫描和绑定。

- 控制台 `/{工作区}/fleet`：「握手并绑定」用注册令牌互证，把本机智能体交给云端，并取回其他已绑定端的智能体与能力。地址留空就是这台协调器。已写在 `data/fleet_link.json` 的地址不会被 `FLEET_CLOUD_URL` 盖回。
- 也可以「扫描本机」后手动勾选。未在控制台确认绑定的设备不接任务。
- 给智能体分配任务在「任务」页。`node_id=auto` 只选当前在线且已绑定该智能体的设备。
- 已绑定端可以 `POST /api/fleet/call` 调用另一台设备上的智能体。绑定列表中的第一个是主智能体。
- 设备有公网地址时：`fleet-edge --mode webhook --webhook-url http://设备:8766/fleet`。签名头 `X-Fleet-Timestamp`、`X-Fleet-Signature`。

云端协调器读不到本机 iCloud。`./scripts/sync-waytoai.sh` 把 WaytoAI 同步到服务器 `/opt/agentcenter/WaytoAI`，并把知识库、技能目录指到其中的 `personalwiki` 和 `skills`。`--install` 之后每 15 分钟一次，日志在 `logs/sync-waytoai.log`。

## 主要 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/super-ai/turn` | 网页对话 |
| POST | `/api/super-ai/device/enroll` | 语音终端登记 |
| POST | `/api/super-ai/device/turn` | 语音终端对话，头 `X-Device-Token` |
| GET | `/api/super-ai/device/tasks/{id}` | 语音终端取回任务播报 |
| GET | `/api/agents` | 智能体（可 `?runtime=`） |
| POST | `/api/tasks` | 创建并执行（可带 `runtime`、`node_id`） |
| GET | `/api/tasks/{id}/stream` | SSE |
| WS | `/ws/tasks/{id}` | WebSocket |
| GET | `/api/fleet/nodes` | 设备、绑定智能体、在线状态 |
| POST | `/api/fleet/handshake` | 本机与云端互证并绑定 |
| POST | `/api/fleet/enroll` | 连接器上报扫描结果并领令牌 |
| POST | `/api/fleet/claim` | 连接器领取一条任务 |
| GET | `/api/knowledge/search` | 卡片检索 |
| GET | `/api/skills` | 双目录技能 |
| GET | `/api/outputs/recent` | 最近产出 |
| GET | `/api/system-status` | 双栈 Gateway / Cron / Sessions |
| GET | `/api/chain?task_id=` | 跨设备信息链（也可用 `run_id` 或 `actor_id`） |

任务状态：`queued` → `running` → `completed` / `failed` / `cancelled`。事件：`text`、`tool_use`、`tool_result`、`status`、`error`、`result`。

## 配置

见 [.env.example](.env.example)。已在控制台改过的知识库目录、技能目录、输出物根，写在 `data/content_roots.json`，启动时不会被 `.env` 盖回。

- `RUNTIMES` / `DEFAULT_RUNTIME`：启用哪些运行时，未指定时用哪个
- `AI_MOCK_MODE`：跳过真实 CLI
- `FLEET_ENROLL_TOKEN`：连接器与语音终端的注册令牌；云端对外时把 `HOST` 改为 `0.0.0.0`
- `KNOWLEDGE_*` / `SKILL_*` / `OUTPUTS_*`：知识库、技能、输出物。细节见 [guide/knowledge.md](guide/knowledge.md)、[guide/skills.md](guide/skills.md)
- `EMBEDDING_PROVIDER`：`hash`（缺省）、`openai` 或 `http`

## CLI

```bash
./scripts/ac health
./scripts/ac agents list
./scripts/ac tasks run coder "写一个 hello world" --wait
./scripts/ac tasks run default "ping" --runtime hermes --wait
./scripts/ac tasks list --status running
```

`--base-url` 或环境变量 `AGENTCENTER_URL`。`--json` 打原始输出。

## 生命周期

| 脚本 | 作用 |
|------|------|
| `./scripts/start-all.sh` | 后端 + 前端 |
| `./scripts/stop.sh` | 停掉两边 |
| `./scripts/status.sh` | 是否在听端口 |
| `./scripts/verify.sh` | 冒烟 |
| `./scripts/fleet-edge.sh` | 转调 `fleet-edge` 包 |
| `./scripts/package-dmg.sh` | macOS DMG（Tauri 2） |
| `./scripts/install-daemon.sh` | 登录自启；外置盘上 launchd 不可用，用登录项 + 看门狗 |

外置盘上的仓库用登录项。看门狗每 60 秒查一次健康并拉起。`./scripts/uninstall-daemon.sh` 卸掉。

桌面包把 **AgentCenter** 拖进「应用程序」。窗口里是静态页，API 由随包的 FastAPI 提供，关窗即停。密钥在 `~/Library/Application Support/AgentCenter/.env`。决策见 [ADR/ADR-002-Tauri桌面打包.md](ADR/ADR-002-Tauri桌面打包.md)。

## 文档

| 文档 | 内容 |
|------|------|
| [guide/architecture.md](guide/architecture.md) | 模块、数据边界、分期 |
| [guide/knowledge.md](guide/knowledge.md) | Personal Wiki 三层 |
| [guide/skills.md](guide/skills.md) | 技能目录与自挖掘 |
| [guide/foropenclaw.md](guide/foropenclaw.md) | 相对 OpenClaw 管理痛点，已经接上什么 |
| [fleet-edge/README.md](fleet-edge/README.md) | 连接器安装与 webhook |
| [ADR/](ADR/) | 知识库内容模型、桌面打包、Wiki 与技能 |
