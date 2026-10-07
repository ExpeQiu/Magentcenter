# 控制台

Next.js App Router。开发端口 **3013**，由仓库根目录 `./scripts/start-frontend.sh` 拉起，不要在这里单独 `npm run dev` 当成 3000。

| 路径 | 页面 |
|------|------|
| `/` | 超级AI |
| `/{slug}/tasks` | 任务。详情是 `tasks/detail?id=` |
| `/{slug}/projects` | 项目 |
| `/{slug}/agents` | Agents |
| `/{slug}/squads` | 小队 |
| `/{slug}/autopilots` | 定时任务 |
| `/{slug}/skills` | 技能 |
| `/{slug}/kanban` | Hermes Kanban |
| `/{slug}/fleet` | 多端关系图谱：云端、设备与智能体 |
| `/{slug}/system` | 双栈状态与告警 |
| `/{slug}/sessions` | 会话。详情是 `sessions/detail?id=` |
| `/{slug}/knowledge` | 知识库 |
| `/{slug}/outputs` | 输出物 |

默认工作区 slug 是 `cyber`。扁平旧路径（如 `/tasks`）由 middleware 转到上次工作区。API 客户端在 `src/lib/api.ts`。
