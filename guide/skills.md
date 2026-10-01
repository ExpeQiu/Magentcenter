# AgentCenter 技能：目录 + 自挖掘

## 定位

技能是组织能力资产，回答「会做什么」。目标是从手工编写，变成成功会话自己长出技能：数量随使用增长，质量来自真实成功案例，复用靠检索后自动注入。

设计来源：`openclaw/小二团队/超级作战队/超级作战队_OpenClaw自动Skill生成实现方案_20260929.md`（2026-09-29，对标 Manus 的技能自动生成）。

正文仍在运行时目录（`~/.openclaw/skills`、`~/.hermes/skills`）。中心负责扫描、安装、下线，以及下面五段引擎的账本。不改运行时加载 `SKILL.md` 的方式。

不搬进本仓库的部分：6 周预算、角色编制、演示视频脚本、技能市场和评级经济。那些是方案里的排期和远期设想。

## 和知识库的关系

| | 知识库（Wiki） | 技能 |
|--|----------------|------|
| 回答 | 知道什么 | 会做什么 |
| 真源 | AgentCenter SQLite | 运行时 `SKILL.md` |
| 互相引用 | L3 `tools` 只存指针 | frontmatter 写 `wiki_ref` |

- 技能的触发词和例子回写一条 Wiki 指针，不把正文灌进知识库。源方案写的 Wiki `skills/` 类别，在这里落在 L3 `tools`。
- Wiki 里稳定的 SOP、决策模式可以升格为技能。
- 检索和 Wiki 用同一套层权重，两路结果一起注入，各自有条数上限。

## 五段引擎

```
调用（任务创建 / 显式「记住这个」）
        │
        ▼
  检索  关键词 + 向量，决策类 ×3.0
        │
        ▼
  存储  SKILL.md + templates/ + examples/ + SQLite 元数据
        ▲
        │
  提炼  抽象、最小输入、步骤、成功标准 → 草稿
        ▲
        │
  捕获  任务收尾快照 → _captured/.../manifest.json
```

### 1. 捕获

任务收尾时记快照。密钥先 redact。

| 信号 | 优先级 | 动作 |
|------|--------|------|
| 「记住这个」「做个技能」「固化下来」 | 最高 | 捕获，并进入提炼 |
| 「干」「好」「收到」「可以」，以及 👍 ✅ 🎯 | 高 | 捕获。不自动提炼 |
| 任务完成且无错误 | 中 | 捕获 |
| 同一类任务 ≥ 3 次 | 低 | 捕获，并提示可以提炼 |

误把闲聊当成技能的代价高于漏掉一次。自动提炼只相信显式标记；正向反馈和任务成功只留快照。

`manifest.json` 字段：`capture_id`、`timestamp`、`session_id`、`agent`、`task_summary`、`user_prompt`、`tools_used`、`steps`、`result`、`user_feedback`、`duration_sec`。另加 `task_id`、`runtime`。

落盘：`<skills-root>/_captured/<date>-<short-hash>/manifest.json`。目录名以 `_` 开头，现有扫描会跳过，不当成可调用技能。运行时若有 inbox 文件，也可作为捕获源。

### 2. 提炼

独立的提炼步骤读 manifest，先回答四件事：这类任务的通用抽象、输入的最小必要项、关键步骤、成功标准。再写成 `SKILL.md`：

- 触发场景
- 输入
- 执行步骤
- 输出
- 模板文件
- 来源（session、提炼日期、验证次数）

并带上 `examples/`、`templates/`。需要时写 `README.md` 和 `tests/`。

质量门槛：自评置信度 ≥ 0.8，步骤清晰度 ≥ 80%，两次重试内能复述同一做法。不够就留 `draft`，不进可调用目录。

frontmatter 继续用现有字段（`name`、`description`、`metadata`），以便 OpenClaw / Hermes 和 html-anything 的 `SKILL.md` 能直接读。额外字段：`status`（`draft` / `verified` / `archived`）、`source_session`、`source_task`、`wiki_ref`。

### 3. 验证

`draft` 不注入。通过条件：人确认，或用同类新说法重跑，结果对得上原会话。每月抽查一成已通过的技能。

失败保持 `draft`。同一条失败满 3 次，移入 `_archive`，退出待验证队列。对应源方案里的「失败三次即删除」，用现有下线目录代替直接删文件。

### 4. 存储

```
<skills-root>/
├── <skill-name>/
│   ├── SKILL.md
│   ├── README.md
│   ├── templates/
│   ├── examples/
│   └── tests/          # 可选
├── _captured/
│   └── <date>-<hash>/manifest.json
└── _archive/
```

磁盘上的 `SKILL.md` 是正文真源。中心 SQLite 只存元数据：名称、描述、触发词、向量、状态、来源会话、创建和更新时间、使用次数、成功率。向量走现有 `EMBEDDING_PROVIDER`，不单独绑某一种嵌入模型。

长期不用、成功率过低的 `verified` 技能自动归档，避免库膨胀。

### 5. 检索

只查 `verified`。关键词精确匹配加向量语义匹配。

| 技能类型 | 权重 |
|----------|------|
| 决策中枢（对应 Wiki L2） | ×3.0 |
| 流程工具（对应 Wiki L3） | ×1.2 |
| 基础数据（对应 Wiki L1） | ×1.0 |

调用时机：创建任务时（对应源方案的 `sessions_spawn`）、拼装 Agent 上下文时、用户显式点名某个技能时。命中条数有上限，和 Wiki 软召回分块注入，避免上下文被技能占满。

使用一次记 `usage_count`；任务成功或失败回写 `success_rate`。

## 初始技能与分类

控制台的初始技能默认读取本机 iCloud `WaytoAI/skills`（`SKILLS_CATALOG_DIR`）。技能页可以改这个目录；空路径恢复默认，改动与知识库写在同一份 `data/content_roots.json`。分类与目录一致：`engineering`、`productivity`、`research`、`domain`、`misc`。`in-progress` 一并列出。`deprecated` 只在包含归档时出现。`catalog/skills.yaml` 补 owner、摘要和是否仅手动触发。

同名技能以仓内这一份为准，不与 `~/.openclaw/skills` 重复列出。仓内技能只读，不下线。自挖掘仍写到运行时目录。

## 和现有能力

保持不变：双目录扫描、安装分流、下线到 `_archive`、审计任务。

自挖掘挂在任务收尾和任务创建两侧。OpenClaw 与 Hermes 共用这五段，只是 `<skills-root>` 不同。把技能暴露成 MCP 工具不在这一期。

## 落地顺序

1. 捕获：manifest、显式标记和任务成功的快照、`_captured` 不出现在技能列表。
2. 提炼：显式标记生成 `draft` 的 `SKILL.md`。
3. 验证：人确认或重跑后变为 `verified`；三次失败进 `_archive`。
4. 检索：`verified` 在下次同类任务的 `system_prompt` 里被引用，并回写用量。

## 风险

| 风险 | 对策 |
|------|------|
| 提炼质量不稳 | 置信度和清晰度门槛；两次重试；每月抽查 |
| 成功判定错误，误生成 | 只有显式标记才提炼 |
| 技能库膨胀 | 低成功率自动归档 |
| 注入污染上下文 | 层权重加条数上限 |
| 和现有技能冲突 | 沿用现有 `SKILL.md` frontmatter |

## 验收

1. 显式「做成技能」留下 manifest，并生成 `draft`。
2. 仅任务成功或一句「好」不会出现在可调用列表。
3. `draft` 和 `_captured` 不会被注入，也不会出现在默认扫描里。
4. `verified` 能在下次同类任务里被引用；决策类排在流程类前面。
5. 同一条验证失败 3 次后进入 `_archive`。
6. 目标（上线后才度量，不是当前成绩）：成功会话捕获率 ≥ 80%，提炼后通过验证 ≥ 70%，自动匹配准确率 ≥ 85%，检索 ≤ 500ms。
