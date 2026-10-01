# agentcenter-fleet

装在跑 OpenClaw 或 Hermes 的机器上。它扫描本机智能体，主动连云端 AgentCenter，领取任务后在本机执行。不需要克隆整个仓库。

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
