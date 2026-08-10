# AgentCenter 知识库内容模型

## 目标

让双运行时（OpenClaw / Hermes）在**下次同类任务**时少踩坑、少重做。  
知识库存的是**可复用经验卡片**，不是 Session 原文堆砌。

## 职责划界

| 资产 | 归属 | 说明 |
|------|------|------|
| `SOUL.md` / `AGENTS.md` / `TOOLS.md` | 运行时自持 | 人格与边界，每会话启动注入 |
| `USER.md` / `MEMORY.md` | 运行时自持 | 用户偏好与 agent 私有精炼记忆（有字数上限） |
| Skills | 运行时技能目录 | 程序性「怎么做」 |
| Outputs vault | AgentCenter 只读浏览 | Obsidian 交付原文，**不并入**检索主库 |
| **中心知识库** | AgentCenter SQLite | 跨 agent / 跨 runtime 的机构记忆 |

**不收录（或仅 archive）**：Session/工具全文默认语料、人格文件副本、密钥/Webhook/Token、Skills 全文。

## 五种卡片

| kind | 含义 | 典型来源 |
|------|------|----------|
| `playbook` | 经验打法（problem/steps/outcome/pitfalls） | 成功任务蒸馏 |
| `precedent` | 先例摘要 + 指针 | 每个完成/失败任务 |
| `incident` | 故障百科 | 失败任务 / Cron repair |
| `artifact_ref` | 产物指针（路径+摘要） | 手工或 Outputs 建指 |
| `shared_fact` | 跨栈共享约定 | 控制台手工创建 |
| `archive` | 原文归档 | Session 手工索引；**默认不检索** |

## 消费契约

1. **任务创建前**：检索 `playbook + precedent + shared_fact`（ops/cron-repair 含 `incident`），注入 `system_prompt` 短块（`KNOWLEDGE_INJECT_ENABLED`）。
2. **任务结束后**：规则蒸馏卡片（Mock 可用；无密钥入库）。
3. **控制台**：按 kind / runtime / workspace 检索，点击溯源到 task / session / outputs。

## API 摘要

- `GET /api/knowledge/search?q=&kind=&workspace_id=&include_archive=`
- `GET /api/knowledge/inject-preview?q=`
- `POST /api/knowledge/entries`（shared_fact 等）
- `POST /api/knowledge/artifact-refs`
- `POST /api/knowledge/backfill`（从任务表蒸馏）
- `POST /api/knowledge/mine-vault`（从 Obsidian `openclaw/` 等子树挖掘指针+高价值蒸馏）
- `POST /api/knowledge/index-session/{id}` → archive

### Vault 挖掘策略

默认 `scope=openclaw`，优先：`0团队通用规则`、案例库、SOP、skills、情报中心。  
每篇建 `artifact_ref`（路径+摘要）；CASE→`incident`，SOP/SKILL→`playbook`，治理总纲→`shared_fact`。  
不整库灌原文。控制台按钮：「从 openclaw 文档挖掘」。

## 配置

```bash
EMBEDDING_PROVIDER=hash
KNOWLEDGE_INJECT_ENABLED=true
KNOWLEDGE_INJECT_TOP_K=3
```

## 验收（DoD）

1. 同类任务第二次创建时，`system_prompt` 含「知识库参考」注入块（Mock 可测）。
2. 失败任务生成 `incident`；ops 检索可命中。
3. 检索结果可跳转 task/session/产物路径；密钥被 redact。
4. 本文与 `architecture.md` 划界一致。
