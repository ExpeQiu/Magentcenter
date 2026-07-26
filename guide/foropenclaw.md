当前 OpenClaw 管理痛点
痛点
现状
任务分散
飞书/Spawn/Sessions 多渠道，缺统一入口
进度黑盒
任务丢出去，不知道跑到哪了
Agent 状态不透明
不知道各 Agent 在干啥、空闲还是忙
Squad 协作无感知
任务委派后，小队成员做了什么看不见
经验不可复用
Session 结束即消失，过程资产流失
AgentCenter 能解决什么
Layer 1 — 任务执行层（当前已实现）
老板/PM → AgentCenter（统一入口）
           ↓
    选择 Squad 或 Agent
           ↓
    POST /api/tasks → SSE 实时看进度
           ↓
    output 存档 → 历史可查

核心价值：替代飞书/Spawn，成为任务提交的"唯一源"
Layer 2 — 监控管理层（Phase 2/3 已实现）
Gateway 状态     → /api/system-status
Cron 健康度     → /api/cron-alerts
Sessions 历史    → /api/sessions
Agent 活跃统计   → /api/agents/stats
Skill 目录      → /api/skills

核心价值：一个 Dashboard 看清楚整个系统
Layer 3 — 真正的"管理"平台（差距）
管理需求
AgentCenter 现状
差距
实时看 Agent 在干啥
只能看到 Session 列表
无法看到 Agent 当前执行到哪一步
控制 Agent 生命周期
无法 spawn/kill 子 Agent
Gateway 不开放此接口
Skill 一键安装/下线
有目录扫描（frontmatter）+ 安装/审核任务 + 下线归档
安装任务可轮询；审核结论本地徽章；详情抽屉看 SKILL.md
任务取消/重试
有 /tasks/{id}/cancel
⚠️ 有接口了
多 Agent 协作可视化
Squad prompt 注入
无法看到子 Agent 协作轨迹
告警推送
仅 Cron error 有 /cron-alerts
缺 Gateway down / 内存告警
Session 回放
仅有列表
无法看到对话详情
真正值得投入的方向
最有价值的 3 件事

1. 任务唯一入口化

废掉飞书/Spawn 提任务，强制所有任务走 AgentCenter
Squad 路由自动委派
任务进度所有人可见
输出自动存档
2. 经验资产化
每个 Session 的输出 → 向量存储 → 可搜索知识库
任务输出自动摘要
历史相同任务可复用
Squad 协作过程可复盘
3. System Health 告警
Gateway down → 飞书告警（5分钟内）
对接现有 ops-monitor.js 数据
告警规则：Cron 连续失败 / 磁盘 > 90% / Session 超时率
推送到飞书群
我建议的优先级
优先级
动作
价值
🔴 P0
强制任务走 AgentCenter（改变工作流）
从分散到统一
🟡 P1
完善 Skill 安装 UI（一键安装/审核/下线）
降低 Skill 管理门槛
🟡 P1
飞书告警接入（Gateway down / Cron 连续失败）
自动化运维
🟢 P2
Session 历史详情页（查看对话内容）
经验可复用
🟢 P2
Cron → Autopilot 同步（双向）
消除重复配置
本质上：AgentCenter 最有价值的是"统一任务入口 + 历史可查 + 状态透明"。