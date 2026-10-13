---
name: agentcenter
description: AgentCenter 协调器 CLI。查询任务、知识库、输出物、会话和多端设备，并在明确授权后创建任务。
version: 0.2.0
metadata:
  cli_command: ac
  requires_install: true
  agent_safe_commands:
    - capabilities
    - health
    - agents-list
    - agents-get
    - tasks-list
    - tasks-get
    - knowledge-search
    - outputs-recent
    - system-status
    - sessions-list
    - fleet-nodes
    - chain
  human_required_commands:
    - tasks-run
    - tasks-cancel
    - tasks-retry
    - squads-run
    - autopilots-create
    - autopilots-trigger
    - autopilots-delete
---

# ac

仓库内入口是 `./scripts/ac`。数据在 stdout，日志在 stderr。

## 前置条件

协调器已在 `http://127.0.0.1:8013` 监听，或设置 `AGENTCENTER_URL`。不连服务时加 `--demo`。

```bash
./scripts/ac --version
./scripts/ac health
```

## 输出

| 写法 | stdout |
|------|--------|
| 默认 | 表格 |
| `--json` | 接口原始 JSON，已有脚本继续用这个 |
| `--format json` | 契约：`module`、`version`、`data_source`、`request_id`、`count`、`items` |
| `-o 文件` | 同样内容写入文件 |

`data_source` 为 `live` 或 `demo`。

退出码：`0` 成功，`1` 参数或业务错误，`2` 无数据或对象不存在，`3` 协调器不可达，`130` 中断。

## Agent 推荐命令

能力目录：

```bash
./scripts/ac capabilities --format json
```

健康检查：

```bash
./scripts/ac health --format json
```

进行中的任务：

```bash
./scripts/ac tasks list --status running --format json
```

查询一个任务。运行中时 `next` 会给出继续查询或订阅的命令：

```bash
./scripts/ac tasks get TASK_ID --format json
```

知识库检索。没有命中时退出码是 2：

```bash
./scripts/ac knowledge search "关键词" --mode hybrid --limit 5 --format json
```

最近输出物、系统概况、会话、设备、信息链：

```bash
./scripts/ac outputs recent --limit 20 --format json
./scripts/ac system status --format json
./scripts/ac sessions list --format json
./scripts/ac fleet nodes --format json
./scripts/ac chain --task TASK_ID --format json
```

离线冒烟：

```bash
./scripts/ac --demo health --format json
```

## 写操作

`tasks run`、`tasks cancel`、`tasks retry`、`squads run`、`autopilots create|trigger|delete` 会改协调器状态。只有用户明确要求时才执行。

创建任务后，stderr 会打印 `accepted task_id=...`。等待超时先用这个 id 查询，不要再创建一次：

```bash
./scripts/ac tasks run coder "做什么" --runtime openclaw --format json
./scripts/ac tasks get TASK_ID --format json
```

`tasks watch` 是事件流，放到后台，不要在对话里一直等。

## 禁止 Agent 自动调用

| 命令 | 原因 |
|------|------|
| `tasks run` / `squads run` / `autopilots trigger` | 会启动智能体 |
| `tasks cancel` / `autopilots delete` | 会取消或删除 |
| `autopilots create` | 会写入定时任务 |

登录、令牌和设备握手不在这个 CLI 里。
