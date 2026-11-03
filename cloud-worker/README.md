# AgentCenter Cloud Worker

独立于 `DEPLOY_PROFILE=cloud` 协调器的执行池进程。协调器保持 `execution_slots=0`；本进程主动 enroll / claim / finish。

```bash
# 开发期委托 fleet-edge / node-agent
AGENTCENTER_URL=https://cloud.example FLEET_ENROLL_TOKEN=... \
  python -m agentcenter_cloud_worker
```

密钥留在 worker 侧；云端只持引用与状态。
