# 云端协调器部署（自建单机）

版本：2026-11-03 · 载体：阿里云 Linux 单机 · Profile：`cloud`

运维真源。架构边界见 [architecture.md](./guide%20from%20codex/architecture.md)；多端能力见 [多端自治升级方案](AgentCenter-多端自治升级方案-2026-10-13.md) Cloud 收窄节。

## 1. 边界

云上只跑协调器：超级AI 入口、云端任务、设备名册、跨端路由、可靠消息、身份与审计、健康检查。

- `DEPLOY_PROFILE=cloud`，`execution_slots=0`，`LOCAL_EXECUTOR_SCAN=off`
- 不扫描、不运行本机 OpenClaw / Hermes；OpenClaw/Hermes「不可用」是预期
- 不挂知识库、技能正文、输出物、小队、Autopilot、Kanban、Tauri
- 执行一律走已登记的 `full` / `edge` / 独立 `cloud-worker`（本轮可不部署 worker）
- `scripts/sync-waytoai.sh` **不是**云端注册流程；禁止把 WaytoAI 镜像写入云端 `content_roots.json`

## 2. 现网约定

| 项 | 默认值 |
|----|--------|
| SSH | `root@47.113.225.93`（`AGENTCENTER_CLOUD_HOST` 可覆盖） |
| 应用根 | `/opt/agentcenter/app`（从旧扁平布局 `backend/` 迁移至此） |
| 数据 | `/opt/agentcenter/data`（与旧布局共用，保留 `node_id`） |
| 日志 | `/opt/agentcenter/logs` |
| 备份 | `/opt/agentcenter/backups/<timestamp>/` |
| 环境文件 | `/opt/agentcenter/app/.env`（首次从旧 `/opt/agentcenter/.env` 迁移；不进 git） |
| 静态前端 | `/opt/agentcenter/app/frontend/out` → `AGENTCENTER_STATIC_DIR` |
| 进程 | systemd `agentcenter-cloud.service` |
| 监听 | `HOST=0.0.0.0` `PORT=8080`（TLS 可后置反代） |

必填环境：`DEPLOY_PROFILE=cloud`、`LOCAL_EXECUTOR_SCAN=off`、`FLEET_ENROLL_TOKEN`；超级AI Key 按需（Mock 验收可 `AI_MOCK_MODE=true`）。

禁止：个人 iCloud / Mac 绝对路径、非空知识库/技能/输出物根。

## 3. 脚本

| 脚本 | 作用 |
|------|------|
| `scripts/cloud/env.cloud.example` | 云端 env 模板 |
| `scripts/cloud/agentcenter-cloud.service` | systemd 单元 |
| `scripts/backup-cloud.sh` | 远端一致性备份 DB / 身份 / env |
| `scripts/deploy-cloud.sh` | 本机构建静态页、rsync、装依赖、装 systemd、健康检查 |
| `scripts/verify-cloud.sh` | 对现网 URL 做协调器验收（不断言本机 CLI 运行时） |

日志：`logs/deploy-cloud.log`、`logs/backup-cloud.log`、`logs/verify-cloud.log`。

`deploy-cloud.sh` **不**调用 `sync-waytoai.sh`。云机不用本机 `scripts/start.sh`（其默认 Mac Application Support 路径）。

## 4. 发布顺序

1. `./scripts/backup-cloud.sh`
2. `./scripts/deploy-cloud.sh`（已有 `.env` 则保留密钥；缺失则从模板生成并写入备份说明）
3. `./scripts/verify-cloud.sh`
4. 最小链路：本机 `full` handshake；ESP32 仍指向 `http://47.113.225.93:8080`（见 `sound/esp32-direct/TOOLS.md`）

## 5. 验收 DoD

- `GET /api/health` → `status=ok` 且 `deploy_profile=cloud`
- 静态首页 HTTP 200
- 无 enroll 令牌时 `POST /api/fleet/enroll` 被拒绝；有令牌可登记（或 verify 用远端已配置令牌冒烟）
- `/api/fleet/enroll`、`/api/fleet/handshake`、`/api/fleet/handshake/accept` 对设备公开（不要求本机会话）；仍校验 `FLEET_ENROLL_TOKEN`
- 云端 `.env` / `content_roots.json` 无个人 iCloud 路径
- 重启后服务可拉起；备份目录可还原 DB 与身份

不纳入本轮协调器 DoD：OpenClaw/Hermes 在云机可用、多副本。

## 5.1 产品增强（P0–P3）

| 级 | 能力 | 落点 |
|----|------|------|
| P0 | outbox peer 用 `events` 信封；lease/ACK | `sync_bus.py`、v2 executions |
| P0 | 窄屏任务环 / PWA | 侧栏抽屉、任务卡片、`manifest`/`sw.js` |
| P1 | WorkItem UI + 外置 Node Agent | `/{slug}/work-items`、`scripts/run-node-agent.sh` |
| P2 | cloud-worker + Router/Mandate | `scripts/run-cloud-worker.sh`、`domain/superagent/` |
| P3 | HTTPS 反代 + 备份校验 | `scripts/cloud/nginx-agentcenter.conf.snippet`、`backup-cloud.sh` integrity |

### Client Session（跨端超级AI）

- 其它端用 `POST /api/v2/clients/enroll`（`FLEET_ENROLL_TOKEN` + 本机 `center_id`）换取 `X-Client-Token`
- 对话：`POST /api/super-ai/client/turn`；不可用于 `claim-next`
- PC full 已绑定云端时，本机 `/api/super-ai/turn` 自动转发云端 Client turn；任务 `origin=super_ai`、`owner_center_id` 为云端
- 验收：`verify-cloud.sh` 含 `client_session` 契约与 enroll+turn 冒烟；详见 [super-agent-alignment.md](./super-agent-alignment.md)

发布后建议：本机 `./scripts/deploy-cloud.sh` → `./scripts/verify-cloud.sh --local-full`；需要 TLS 时套用 nginx 片段。

## 6. 回滚

```bash
ssh root@47.113.225.93 'systemctl stop agentcenter-cloud'
# 从 /opt/agentcenter/backups/<ts>/ 还原 agentcenter.db、node_identity.json、.env
# 必要时还原上一版 /opt/agentcenter/app
ssh root@47.113.225.93 'systemctl start agentcenter-cloud'
curl -sf http://47.113.225.93:8080/api/health
```

禁止两台活跃节点共用同一 `node_id`。

## 7. 与 sync-waytoai 的切割

`sync-waytoai.sh` 仅人工把本机 WaytoAI 拷到他机（默认目标 `/opt/agentcenter/WaytoAI`）。该目录**不得**作为协调器内容根；云端注册、content_roots、知识/技能路径一律不引用它。
