# AgentCenter Node Agent

PC / edge 上的独立执行进程：领取任务、目录授权、工具白名单、结果回传。

本地核心（FastAPI）只调度与持久化；本进程复用 `fleet-edge` 协议（enroll / heartbeat / claim / finish），并增加本地执行租约续约。

```bash
# 开发：复用 fleet-edge 入口，后续拆独立包
pip install -e ../fleet-edge
AGENTCENTER_URL=http://127.0.0.1:8013 FLEET_ENROLL_TOKEN=... fleet-edge
```

环境变量见 `fleet-edge/README.md`。过渡期 Core 内仍可内嵌 adapter（`LOCAL_EXECUTOR_SCAN`）；新安装默认外置本 Agent。
