# AgentCenter 知识库：Personal Wiki

## 定位

知识库是决策中枢，回答「知道什么」。技能回答「会做什么」，见 [skills.md](./skills.md)。两边互相留指针，不复制全文。

设计态来源：`Github/3-POC技术验证/personal wiki.md`（Personal Wiki v1.0，2026-09-24）。飞书同文：[JInTd7RsSoiIoExRtkkcG7dQneg](https://r4kh7idol1.feishu.cn/docx/JInTd7RsSoiIoExRtkkcG7dQneg)。

三件事：

1. **了解使用者**：L1 的身份、现状、偏好、共享事实。
2. **了解决策逻辑**：L2 的模型、模式、原则、拍板、教训、先例。
3. **指导 Agent**：高风险先过门，决策前软召回，做完写复盘。

不搬进本仓库的部分：方案里的 164 条、召回 284、效率 +195%、Hermes cron ID、`~/.hermes/scripts/` 下未落地的 13 个脚本。那些是设计态数字或 Hermes 侧工程，AgentCenter 只保留结构。

## 三层

召回分 = 关键词/向量混合分 × 层权重。同相关度时 L2 压过 L3 和 L1。

| 层 | 权重 | 子目录 | 放什么 |
|----|------|--------|--------|
| L2 模式与决策 | ×3.0 | `mental-models` `patterns` `principles` `decisions` `reflections` `experiences` | 思维模型、反复打法、原则、重大拍板、单次教训、事件先例 |
| L3 流程与工具 | ×1.2 | `procedural` `templates` `tools` | SOP、模板、工具索引 |
| L1 事实 | ×1.0 | `profile` `state` `preferences` `semantic` | 静态事实、当前状态、偏好、共享约定 |
| notes | 不参与默认召回 | `notes` | 执行日志、Session 原文 |

L1 再分时效：`profile` / `semantic` 长期有效；`state` 按周或月更新；`preferences` 在复盘里出现明确拍板时增量写入。

`reflections` 重复出现后，提炼成一条 `patterns`，不删原教训。

## 路由

所有写入和召回经过同一张路由表（方案里的 `layer_resolver`），不在各接口里各写一套目录判断。

| 旧 kind | 新位置 |
|---------|--------|
| `playbook` | L3 `procedural` |
| `precedent` | L2 `experiences` |
| `incident` | L2 `reflections` |
| `shared_fact` | L1 `semantic` 或 `preferences` |
| `artifact_ref` | L1 指针（路径 + 摘要） |
| `archive` | `notes` |

旧 `kind` 保持可读。新写入带 `layer` + 子目录。历史缺层的条目用回填补上，不覆盖正文。

## 任务上的五步

对应方案 P0–P4，挂在 AgentCenter 任务上，不做成 Hermes 命令钩子。

| 步骤 | 作用 | 何时 |
|------|------|------|
| P0 门禁 | 高风险（发布、凭证、修复生产）必须先召回到依据，或显式跳过 | 派发前 |
| P1 软召回 | 决策前召回 L2 + L3 + L1，L2 ×3.0，注入短块 | 创建任务时，可关 |
| P2 打标 | 写入前建议 `src:*` `topic:*` `type:*` `status:*`，并提示近重复 | 入库前 |
| P3 复盘 | 收尾后写 `experiences`；失败再写 `reflections`；若改了偏好或状态，同步 L1 | 任务结束；也可定时补扫 |
| P4 跨源 | 飞书 / Wiki / session 按主题互链 | 主动查，不进默认注入 |

普通任务只走 P1 和 P3。P0、自动召回只对高风险打开，避免每次任务都塞一屏历史。

## 四件自动化

| 件 | 作用 |
|----|------|
| 自动路由 | 新条目按路由表进层；判不准时保留手工指定的层 |
| 自动召回 | 仅高风险，低于相关度阈值的不注入 |
| 健康扫描 | 每周查缺层、过期 `state`、近重复、泄漏的密钥 |
| 看板 | 各层条数、召回命中、跳过门禁的次数。不报未测量的效率百分比 |

## 职责划界

| 资产 | 归属 |
|------|------|
| `SOUL.md` / `AGENTS.md` / `TOOLS.md` / `USER.md` / `MEMORY.md` | 运行时自持 |
| Skills 正文 | 运行时技能目录 |
| Outputs vault | 只读浏览，不并入检索 |
| **中心 Wiki** | AgentCenter SQLite，跨 agent / 跨 runtime |

不收录：Session 全文（除非显式归档到 notes）、人格文件副本、密钥、Skill 全文。入库和注入前 redact token / webhook / `sk-`。飞书同步用来源记录哈希做幂等。

Wiki 里稳定的 SOP 可以升格为技能。技能只在 L3 `tools` 留一条指针。

## 配置

默认读取本机 iCloud `WaytoAI/personalwiki`。控制台知识库页可以改目录；空路径恢复默认。改动记在 `data/content_roots.json`，优先于环境变量。目录里的 Markdown 按子目录归层（如 `decisions/` → L2），不复制进数据库。

```bash
KNOWLEDGE_WIKI_DIR="/Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/personalwiki"
EMBEDDING_PROVIDER=hash
KNOWLEDGE_INJECT_ENABLED=true
KNOWLEDGE_INJECT_TOP_K=3
# 层权重：L2,L3,L1
KNOWLEDGE_LAYER_WEIGHTS=3.0,1.2,1.0
```

## 验收

1. 同相关度下，L2 排在 L3、L1 前面。
2. 新条目带 `layer` 和子目录；旧 `kind` 能映射。
3. notes 默认不进注入块。高风险任务可跳过门禁，并留下记录。
4. 复盘能写下先例；明确的偏好变更会增量写入 L1 `preferences`。
5. 密钥被 redact。与 [skills.md](./skills.md)、[architecture.md](./architecture.md) 的划界一致。
