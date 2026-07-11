# AgentCenter 架构设计

## 定位

OpenClaw 专用 Agent 编排中台，独立自研，吸收 Multica 核心思想：

- **Agent 即队友**：从 `openclaw agents list` 同步档案
- **任务生命周期**：queued → running → completed/failed/cancelled
- **统一运行时**：封装 `openclaw agent` CLI（local / gateway）
- **实时进度**：SSE + WebSocket 推送事件

## 架构图

```
调用方 (HTTP/WS/脚本)
        │
        ▼
  FastAPI Backend
  ├── AgentRegistry   ← openclaw agents list
  ├── TaskManager     ← 生命周期 + SQLite
  └── OpenClawAdapter ← openclaw agent --local --json
        │
        ▼
   openclaw CLI
```

## 核心模块

### AgentRegistry

- 调用 `openclaw agents list --json`
- 60s 内存缓存
- JSON 失败时降级文本解析

### OpenClawAdapter

- 版本门禁（最低 2026.5.5）
- 参数：`--local --json --agent <id> --session-id --message`
- 输出解析：整段 JSON 优先，NDJSON 降级
- system_prompt 拼入 message（OpenClaw 不支持 --system-prompt）

### TaskManager

- SQLite 持久化任务与事件
- 同 Agent 串行执行（可配置）
- 全局并发上限（默认 3）

## 事件类型

`text` | `tool_use` | `tool_result` | `status` | `error` | `result`

## 分期路线

- **Phase 1**（当前）：API 网关 + 任务引擎
- **Phase 2**：Next.js 控制台
- **Phase 3**：Squads 路由 + Autopilot + 技能目录
