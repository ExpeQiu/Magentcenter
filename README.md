# AgentCenter

OpenClaw 专用 Agent 编排中台。参考 Multica「Agent 即队友、任务生命周期、统一运行时」理念，提供 REST API + SSE/WebSocket 实时事件流。

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
| GET | `/api/agents` | 列出 OpenClaw Agent |
| POST | `/api/tasks` | 创建并执行任务 |
| GET | `/api/tasks/{id}` | 任务详情 |
| GET | `/api/tasks/{id}/stream` | SSE 事件流 |
| WS | `/ws/tasks/{id}` | WebSocket 事件流 |

## 配置

见 [.env.example](.env.example)。关键项：

- `AI_MOCK_MODE=true` — 跳过真实 OpenClaw 调用
- `OPENCLAW_MODE=local|gateway` — 执行模式
- `OPENCLAW_EXECUTABLE=openclaw` — CLI 路径

## CLI

```bash
./scripts/ac health
./scripts/ac agents list
./scripts/ac tasks run coder "写一个 hello world" --wait
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

## Phase 3 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/squads` | 列出预置小队 |
| POST | `/api/squads/tasks` | 向小队 leader 分配任务 |
| GET | `/api/skills` | 扫描 OpenClaw 技能目录 |
| GET/POST | `/api/autopilots` | 定时任务管理 |

## 架构

详见 [guide/architecture.md](guide/architecture.md)
