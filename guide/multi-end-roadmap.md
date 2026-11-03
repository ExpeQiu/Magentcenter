# 多端五阶段改造路线图（实施索引）

完整 DoD 与缺口对照见 Cursor 计划「多端五阶段改造」。本文件跟踪仓库内落地索引。

| 阶段 | 主题 | 主要落点 | 状态 |
|------|------|----------|------|
| 0 | 文档对齐 | README、ADR-002/004、`super-agent-alignment.md` | 已落地 |
| 1 | 身份 + Node Agent | `ChannelRecord`、voice/connector 共存、`node-agent/`、`verify` 无云闭环 | 骨架已落地 |
| 2 | PWA + WorkItem | `frontend/public` PWA、`work_items`/`conversations`/`triggers`、Artifact availability | 骨架已落地 |
| 3 | Delivery + Supervisor | execution lease、ACK 三分、跨中心 outbox peer 投递、`supervisor.py` | 骨架已落地 |
| 4 | 语音 Channel / 硬件 | `/api/v2/channels/interrupt`、硬件指令 `expires_at` / 急停 | 骨架已落地 |
| 5 | Router / Mandate / worker | `domain/superagent/`、`cloud-worker/` | 骨架已落地 |
| 运维 | 云端自建单机发布 | [cloud-deploy.md](./cloud-deploy.md)、`scripts/deploy-cloud.sh` / `backup-cloud.sh` / `verify-cloud.sh`、systemd | 已落地 |

## PC 产品轨（App + 本地核心 + Node Agent）

目标真源：[guide from codex/multi-end-design.md](./guide%20from%20codex/multi-end-design.md)。与上表云端五阶段并列，不互相替代。

| 阶段 | 主题 | 主要落点 | 状态 |
|------|------|----------|------|
| PC-0 | 验收口径 | 本表四条 DoD | 已落地 |
| PC-1 | 生命周期与身份 | `core.pid` / `node-agent.pid`、Tauri 启停、`node_identity.json` 对齐 | 已落地 |
| PC-2 | Node v2 主路径 | claim-next / lease / ACK / finish；外置优先；内嵌回退 | 已落地 |
| PC-3 | 无云闭环验收 | `verify.sh` + `test_autonomy` + 无云 E2E | 已落地 |
| PC-4 | 会话与产物 | conversations 持久化、ArtifactRef availability 单测 | 已落地 |
| PC-5 | 联网协同（PC 侧） | `CLOUD_INBOUND_SLOTS`、revoke-local、`verify-cloud --local-full` | 已落地 |

### PC 产品轨 DoD

1. 全新安装不填云地址即可建任务、执行、查产物。
2. 关窗后任务可继续；显式停止后不再 claim。
3. 云不可达时本地任务可跑；远程步骤显示等待或失败。
4. Node Agent 用 v2 租约；迟到回写被拒。

云端产品 P0–P3 增量（2026-11-03）：outbox `events` 修复、窄屏任务/WorkItem UI、外置 node/cloud-worker 脚本、nginx HTTPS 片段、备份 integrity。跨机全链路与 chaos 仍需现网 `verify-cloud.sh --local-full` 补齐。

非目标：跨云联邦、全量库同步、cloud 协调器隐式开执行槽；本 PC 轨不交付完整手机 App / 硬件固件。
