# 对照 OpenClaw：已经接上的管理能力

这份说明对的是早期痛点：任务散在飞书和各 Session、进度看不见、技能和告警没有统一入口。下面按当前代码写，不再沿用当时的缺口清单。

## 已经接上

| 痛点 | 现在 |
|------|------|
| 任务没有统一入口 | `POST /api/tasks`，控制台「新建任务」，CLI `./scripts/ac tasks run`。超级AI 建任务必须先确认 |
| 进度黑盒 | 任务状态机 + SSE `/api/tasks/{id}/stream` + WebSocket。事件含 `text`、`tool_use`、`tool_result` |
| Agent 是否空闲 | `/api/agents/stats`，控制台 Agents |
| 小队委派看不见 | Squad 任务打到 leader；Kanban Swarm 图看协作 |
| 经验随 Session 消失 | 知识库三层卡片，任务结束写复盘；Session 可索引进 archive，默认不参与召回。详见 [knowledge.md](./knowledge.md) |
| 技能只有目录 | 双运行时扫描、安装、下线；成功任务可捕获，显式提炼并验证后才注入。详见 [skills.md](./skills.md) |
| 取消不了 | `POST /api/tasks/{id}/cancel`，以及 retry |
| 只有 Cron 红点 | Gateway、Cron、磁盘阈值；规则在 `/api/settings/alert`，可推飞书。配置见 [FEISHU_WEBHOOK_SETUP.md](./FEISHU_WEBHOOK_SETUP.md) |
| Session 只有列表 | `/{slug}/sessions/detail?id=` 看对话 |

系统健康在 `/{slug}/system`：双栈 Gateway、Cron、Sessions 一次看完。

## 仍然不在中心里做

- 不通过 Gateway 去 spawn 或杀掉子 Agent。运行时进程仍由 OpenClaw / Hermes 自己管。
- 事件流能看到工具调用和文本，不是运行时内部的单步调试器。
- 告警覆盖 Cron 失败、Gateway 不可用、磁盘占比。没有 Session 超时率，也没有去读某份 `ops-monitor.js`。
- 超级AI 只转发白名单服务，不另外长出一套任务或知识库。
