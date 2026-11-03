# AgentCenter Node Agent

PC / edge 上的独立执行进程：v2 `claim-next`、租约续约、delivery ACK、目录白名单、结果 `finish`。

本地核心（FastAPI）只调度与持久化；本进程读取与 Core 同一数据目录的 `node_identity.json` 与 `node_agent.token`（Core 启动时写入）。

```bash
# 推荐：仓库根脚本
AGENTCENTER_URL=http://127.0.0.1:8013 \
  ./scripts/run-node-agent.sh

# Mock（不调用本机 CLI）
FLEET_MOCK=1 ./scripts/run-node-agent.sh --once
```

环境变量：

| 变量 | 含义 |
|------|------|
| `AGENTCENTER_URL` | Core 地址 |
| `AGENTCENTER_DATA_DIR` | 与 Core 共用；读 `node_identity.json` / `node_agent.token` |
| `NODE_AGENT_TOKEN` | 可选，覆盖 token 文件 |
| `FLEET_MOCK=1` | 不调用 OpenClaw/Hermes |
| `LOCAL_EXECUTOR_SCAN` | Core 侧：`off` 仅外置；`auto` 检测本进程 PID 后外置；`on` 内嵌 |

过渡期 Core 仍可内嵌 adapter；新安装优先外置本 Agent（`start.sh` 在配置了 `FLEET_ENROLL_TOKEN` 或 `START_NODE_AGENT=on` 时拉起）。
