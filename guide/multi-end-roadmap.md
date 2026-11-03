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

端到端跨机 / 故障注入完整验收仍需按各阶段 DoD 继续补齐。非目标：跨云联邦、全量库同步、cloud 协调器隐式开执行槽。
