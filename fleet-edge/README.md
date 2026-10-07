# agentcenter-fleet

装在跑 OpenClaw 或 Hermes 的机器上。它扫描本机智能体，和云端握手后绑定这些资源，并取回其他端的资源与能力，再领取任务在本机执行。不需要克隆整个仓库。

```bash
pip install .
export FLEET_ENROLL_TOKEN=与云端相同
export AGENTCENTER_URL=http://云端:8013
fleet-edge
```

设备标识默认用主机名。令牌写在 `~/.agentcenter/<节点>.token`，日志在 `~/.agentcenter/logs/fleet-edge.log`。

设备有公网地址时：

```bash
fleet-edge --mode webhook --webhook-url http://设备:8766/fleet
```

`FLEET_MOCK=1` 只验证领取，不调用本机 CLI。控制台确认绑定之后才会接到任务。

已绑定后，连接器可以用设备令牌调用其他端的智能体：`POST /api/fleet/call`（`Cloud.call_agent`）。云端把任务派到那一台，由对方领取并执行。
