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
