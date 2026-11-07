# 飞书 Webhook 配置指南

出站（告警 / 超级AI 回帖）用群机器人 Webhook；入站（@机器人 → 超级AI）用事件订阅回调。

## 出站：群机器人 Webhook

1. 打开目标飞书群 → 设置 → 群机器人 → 自定义机器人
2. 复制 Webhook URL（`https://open.feishu.cn/open-apis/bot/v2/hook/xxx`）
3. 写入 `.env`：

```bash
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/你的实际URL
CRON_ALERT_INTERVAL=300
```

4. 重启：`./scripts/stop.sh && ./scripts/start-all.sh`
5. 验证：`curl -sf http://localhost:8013/api/cron-alerts`

告警条件：Cron 首次变 `error`；间隔由 `CRON_ALERT_INTERVAL`（默认 300s）控制。

## 入站：事件订阅 → 超级AI

1. 飞书开放平台创建企业自建应用，开通「接收消息」等权限，订阅 `im.message.receive_v1`
2. 请求地址填：`https://<你的公网>/api/sources/feishu/events`（需可被飞书访问）
3. 将 Verification Token 写入 `.env`：

```bash
FEISHU_VERIFICATION_TOKEN=你的VerificationToken
```

4. 重启后完成 URL 校验（接口对 `url_verification` 回传 `challenge`）
5. 群聊须 @ 机器人；单聊直接进超级AI。同 `message_id` 幂等去重。
6. Policy Gate 来源 `feishu`；出站回帖复用 `FEISHU_WEBHOOK_URL`

快速探测：

```bash
curl -s http://localhost:8013/api/sources/feishu/events \
  -H 'Content-Type: application/json' \
  -d '{"type":"url_verification","challenge":"ping","token":"'$FEISHU_VERIFICATION_TOKEN'"}'
```

## 目标群（示例）

- **统一推送群**：`oc_f734d856374cfe9e228a222d02f9e75f`
- **情报中心群**：`oc_ffd151ec2bf245e9332226bd1701fed6`
