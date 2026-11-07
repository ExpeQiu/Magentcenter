# DeepSeek Super-agent 与 AgentCenter 对照

日期：2026-11-03。依据 DeepSeek Harness「Super-agent 设计探索」(2026-10-31) 与 WaytoAI-space 云端超级AI设计稿。

## 借鉴边界

吸收：角色分离、事件准入、Context Reference、授权凭据、持久化副作用。  
不引入：dsh-superagent-prototype TypeScript 运行时、Cordis 插件内核。

## 角色映射

| DeepSeek | AgentCenter | 阶段 |
|----------|-------------|------|
| Environment Event | Trigger / 接入 API 落盘 | 2+ |
| Preprocessing + Context Reference | Gate + Context Broker；禁止云端直读 PC 裸路径 | 2–3 |
| Router | 结构化 `reply/accept/revise/stop/...`；不持工具 | 2 最小 → 5 |
| Worker Session | Node Agent / fleet-edge / 独立 cloud worker | 1 → 5 |
| Tool Calling | 仅节点侧适配器；cloud 零槽 | 1、5 |
| Session Merge | WorkController + ArtifactVersion/Review | 2–3 |
| Multi-party | Attention Inbox / 通知 | 2、4 |
| Watchdog | 确定性 Supervisor + 语义 Watchdog（只建议） | 3 → 5 |

## 刻意不照搬

- 无限增长单会话上下文 → workspace+Thread 有界评估  
- Worker 与 Router 抢同一句话 → Controller 释放归属后才新 Eval  
- Watchdog 自动扩权/改需求 → 语义层只提醒；自修复仅基础设施重试  

## 两层关系

多端层（身份、投递、PWA、语音）与 Super-agent 控制面（Trigger→Router→WorkController→Delivery）叠加，不互相替代。`TaskRecord` / `ExecutionRecord` 保留为执行请求与事实。

## 源码对照结论（2026-11-07）

本地细读仓库：`/Users/qiubin/gitcom/dsh-superagent-prototype`（DeepSeek 官方 MIT 原型）。  
可移植：`src/core/*` 域状态机、Policy Gate、Subscription 扇出、Outbox 有序回写、Attention 结构化提问。  
不引入：DSH Cordis bundle、router/worker preset、tmux profile、GitHub-only 单仓绑定。

现状：主流量仍走 `super_ai.handle_turn` → `TaskManager`；`domain/superagent/` 与 `WorkItem`/`Mandate`/`Attention` 为平行骨架，未接管派发。

## 改造清单（按优先级）

### P0 — 接通已有骨架（≤2 天/项）

| # | 项 | 状态 | 落点 |
|---|----|------|------|
| 1 | Mandate 执法 | 已落地 | cancel / claim-next / finish |
| 2 | Router 接管 | 已落地 | stop / revise / attach / accept / ignore |
| 3 | Trigger → Gate | 已落地 | `policy.gate`；未授权来源不建单 |
| 4 | Attention Inbox | 已落地 | `/api/v2/attention` + dismiss；前端「待办」 |

### P1 — 域模型对齐（每项 2–4 天）

| # | 项 | 状态 | 落点 |
|---|----|------|------|
| 5 | WorkController | 已落地 | `controller.resolve_followup` / `attach_followup` |
| 6 | Policy 版本 | 已落地 | `domain/superagent/policy.py`；`observe`/`auto`/`off` |
| 7 | Outbox 有序回写 | 已落地 | `core/delivery.py`；`wi:{id}:{seq}:{kind}` |
| 8 | 沉默交付 | 已落地 | finish 只入队 result/failed；丢弃 progress |

### P2 — Source 与并行（按需）

| # | 项 | 状态 | 落点 |
|---|----|------|------|
| 9 | 飞书入站 Source | 已落地 | `POST /api/sources/feishu/events` → Trigger + Gate + `handle_turn`；出站复用 `FEISHU_WEBHOOK_URL` |
| 10 | Worker 槽位 | 已落地 | `WorkerSlotPool`；同 session 不并发；满槽回 queued |
| 11 | Panel 健康三问 | 已落地 | `GET /api/v2/superagent/overview` + 前端 `OverviewStrip`（健康态紧凑） |

### 明确不做

- 依赖 `@deepseek-ai/dsh` / Cordis 插件内核
- 云端直读 PC 裸路径（继续 Context Reference / ArtifactRef）
- Watchdog 自动扩权或改需求（语义层只建议）
- 无限增长单会话；评估上下文保持 workspace+Thread 有界

### 验证钩子

- 单测：`backend/tests/` 补 Mandate gate、Router stop/revise、Trigger 幂等
- `./scripts/verify.sh` 增加「建单→执行→attention→stop 撤权」路径
- 日志键：`trigger_id`、`work_item_id`、`mandate_id`、`decision`、`policy_version`

## 云端超级AI + Client Session（2026-11-07 落地）

定案：经超级AI 发起的任务一律由云端分发；任务台/Autopilot 等本地建单 `origin=local` 不上云。鉴权用 **Center/Client Session**（`X-Client-Token`），与 Node Token 互斥。

| API | 用途 |
|-----|------|
| `POST /api/v2/clients/enroll` | `FLEET_ENROLL_TOKEN` + `center_id` → `client_token` |
| `POST /api/v2/clients/refresh` / `revoke` | 轮换 / 作废 |
| `POST /api/super-ai/client/turn` | 跨端对话（云端编排） |
| `GET /api/super-ai/client/session/{id}` | 会话历史 |
| `GET /api/super-ai/client/tasks/{id}` | 只读任务进度 |

PC 联网协同：本机 `POST /api/super-ai/turn` 检测远程 `fleet_link` 后自动 enroll Client Session 并转发云端；断云返回明确错误，不静默改本地建单。Router stop 撤 Mandate；claim/cancel 执法 `task.execute` / `task.cancel`。

契约：`x-features.client_session=1`；任务 `origin=super_ai|local`。

## P0–P1 续作（2026-11-07）

- Policy：`GET|PUT /api/v2/superagent/policy`；默认 `observe`
- Attention：侧栏「待办」`/{slug}/attention`；`POST .../dismiss`
- Deliveries：`GET /api/v2/work-items/{id}/deliveries`
- 同一 `session_id` 后续话默认 attach 到进行中 WorkItem；「新建任务」才强制新开
- 单测：`tests/test_superagent_p0_p1.py`

## P2 续作（2026-11-07）

- 飞书：`FEISHU_VERIFICATION_TOKEN` + `guide/FEISHU_WEBHOOK_SETUP.md`（入站/出站）
- 槽位：`core/worker_slots.py` 与 `TaskManager._run_task` 联动
- Overview：`core/overview.py`；超级AI 页顶栏三问条
- 单测：`tests/test_p2_feishu_slots.py`
