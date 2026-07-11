# 飞书 Webhook 配置指南

## 获取 Webhook URL

### 方式一：通过飞书群机器人（推荐）

1. 打开目标飞书群
2. 设置 → 群机器人 → 添加机器人 → 自定义机器人
3. 机器人名称：`AgentCenter Alert`
4. 安全设置：选择「使用签名校验」或「IP地址段」
5. 复制 Webhook URL（格式：`https://open.feishu.cn/open-apis/bot/v2/hook/xxx`）

### 方式二：使用 lark-cli 创建

```bash
# 查看现有机器人
lark-cli bot list

# 获取群信息
lark-cli im chats list
```

## 配置步骤

1. 编辑 `.env` 文件：
```bash
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/你的实际URL
CRON_ALERT_INTERVAL=300
```

2. 重启 AgentCenter：
```bash
cd ~/Mgit/AgentCenter && ./scripts/stop-all.sh && ./scripts/start-all.sh
```

## 验证告警

确认配置后，触发一个 Cron error 检查，看飞书群是否收到消息：

```bash
curl http://localhost:8013/api/cron-alerts
```

## 告警触发条件

- Cron 任务状态变为 `error`
- 同一任务只在首次出错时告警（防止重复）
- 告警间隔：`CRON_ALERT_INTERVAL` 秒（默认 300s = 5分钟）

## 目标群

- **统一推送群**：`oc_f734d856374cfe9e228a222d02f9e75f`
- **情报中心群**：`oc_ffd151ec2bf245e9332226bd1701fed6`
