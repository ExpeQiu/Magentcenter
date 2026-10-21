# AgentCenter 项目评估

评估日期：2026-10-16（北京时间）  
评估目录：`/Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter`  
基线：当前工作目录；最近提交 `8307b7d`，2026-10-15。工作目录包含大量暂存和未暂存修改，因此本报告不等同于对该提交或已发布安装包的认证。

## 判断

**值得继续投入，已具备内测基础；下一阶段应从功能扩展转向权限、可靠性和发布质量。当前不适合直接作为面向不可信客户端的公网服务发布。**

最有价值的定位是：统一管理本机及多台设备上的 OpenClaw / Hermes 执行、任务结果和运行记录。双运行时、多端连接器、任务事件、知识卡片和技能账本已有实际代码，超过了界面原型的阶段。

当前主要约束来自两方面：一是身份边界尚未一致落到所有接口；二是新协议的持久化结构比实际传输、恢复和结果应用更完整。页面和概念的广度已经领先于可验证的运行保障。

适用阶段判断：个人受控环境可继续试用；小范围内测应先修复下面的 P0 项；公网或不可信多客户端环境暂不建议发布。没有把工作区筛选当作多租户安全隔离。

## 实现基础

- 后端 84 个 Python 文件、21,885 行；前端 83 个 TS/TSX 文件、13,404 行；连接器 4 个 Python 文件、691 行。合计 35,980 行，未计桌面 Rust、固件、测试及生成文件。规模统计用于判断维护面，不代表质量评分。
- 22 个测试文件，共 123 个现有测试。覆盖 CLI 契约、设备绑定、任务状态、去重、工作区映射、文件边界、知识与技能等。
- FastAPI、SQLAlchemy/SQLite、Next.js、Tauri、标准库连接器的分工清楚；运行时适配器避免前端直接依赖各 CLI 的输出格式。
- 任务事件持久化；SSE/WS 按游标读取。重启后将不可核验的执行标成 `needs_attention`，避免盲目重跑有副作用的工作，这个取舍合理。但尚不等于自动接管或恢复执行。
- 知识、技能、输出物分开建模；输出物路径逃逸有测试，HTML 预览禁脚本；节点令牌哈希存储、短码配对和日志脱敏已有基础。

## 必须优先处理的发现

### F1 · P0 · 任意非空设备令牌头可以绕过管理接口的会话门禁

`local_session_guard` 看到 `X-Node-Token` 或 `X-Device-Token` 就直接放行，没有在该分支验证令牌。普通任务和设置接口也没有对应的设备身份验证。

在实际应用对象上使用隔离的任务管理器复现：同一 `GET /api/tasks?include_live=false`，无凭据返回 401；带一个无效的节点令牌头返回 200；无效的设备令牌头也返回 200。没有访问真实任务或真实服务。

影响：能够访问 API 的客户端，可能绕过控制台门禁读取管理数据或调用写接口；调用具体业务后的影响取决于对应接口。对外部署是发布阻断项。

建议：统一解析并验证身份；按接口声明允许的人类会话、管理员、执行节点或对话设备身份。设备身份不能因头存在就获得管理权限。

证据：[main.py:150](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/backend/app/main.py:150>)、[tasks.py:23](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/backend/app/api/tasks.py:23>)。

验收：无效令牌全部拒绝；有效对话设备不能创建管理员注册券、修改内容目录或直接调用普通管理接口；合法设备接口仍可工作。

### F2 · P0 · 任务 WebSocket 没有鉴权

`/ws/tasks/{task_id}` 接受连接后直接读取任务与事件，没有验证会话、设备身份或任务归属。HTTP 中间件不会自动保护 WebSocket。

在实际路由上，以隔离的任务与事件替身复现：没有提交任何凭据，也能连接并收到结果事件。该复现使用虚构任务标识，没有读取真实任务。

影响：在知晓或获得任务 ID 后，可以读取任务事件；任务 ID 的随机性不能替代权限判断。

建议：接受连接前校验身份和对象权限，并校验允许的 Origin；与 SSE 共用任务读取授权逻辑。

证据：[ws.py:14](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/backend/app/api/ws.py:14>)。

验收：匿名、失效会话和无任务权限连接均失败；合法连接能按游标恢复。

### F3 · P0 · v2 领取执行只检查角色，没有核对目标节点

`claim_command` 验证节点令牌与角色之后，直接把客户端提交的任务或委托 ID 交给 `accept_remote`。没有核对任务是否存在、是否分配给该节点，或委托的目标与授权范围。

在临时数据库复现：任务明确分配给节点 A；持有合法 edge 身份的节点 B 领取该任务时返回 `accepted=true`，生成的 execution 归属于 B。

影响：一个已注册节点可以抢占其他节点的执行去重键，污染执行归属。该接口本身不返回任务正文，但已经破坏调度授权。

建议：读取真实命令及目标后再领取；检查目标节点、拥有者、工作区授权和 attempt；将检查与领取放入同一原子事务。

证据：[v2.py:263](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/backend/app/api/v2.py:263>)、[execution.py:70](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/backend/app/core/execution.py:70>)。

验收：B 不能领取 A 的任务；不存在、过期或不匹配 attempt 的命令拒绝；同一合法领取的重放返回一致结果。

### F4 · P1 · v2 可靠消息尚未形成端到端闭环

委托与 outbox 同事务写入是良好的基础，但仓库中 `pending_outbox`、`ack_outbox` 没有生产调用方；`ingest` 目前记录收件箱并确认，没有把事件应用到任务或执行状态；`/commands/ack` 返回 `acked=true`，没有持久化该确认。现有 fleet-edge 仍调用 v1 的 claim/finish。

影响：不能仅凭 outbox/inbox 表和去重测试，认定跨中心可靠投递与结果收敛已经完成。这里的结论针对 v2，不是否定现有 v1 领取和回写路径。

建议：先选定一条实际部署主路径，补上发件重试、接收授权、业务应用与去重同事务、持久化确认、状态收敛和重启恢复。若 v2 仍为实验功能，应在产品和文档中标注。

证据：[sync_bus.py:70](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/backend/app/core/sync_bus.py:70>)、[sync_bus.py:136](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/backend/app/core/sync_bus.py:136>)、[v2.py:296](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/backend/app/api/v2.py:296>)。

验收：断网、重复投递、接收后崩溃、确认丢失和双方重启后，任务最终状态能收敛，执行副作用不重复发生。

### F5 · P1 · 连接器结果回传失败后没有持续补发

`execute_and_finish` 把结果写入本地 outbox，回传失败后仅记录异常。补发发生在启动阶段，或重复收到同一个任务时；正常主循环和心跳不定期扫描待回传结果。服务端领取时已把任务改为 running，正常轮询也不会再次领到该任务。

在隔离连接器复现：模拟执行完成、回传暂时失败，结果留在 pending；检查主循环后未找到持续重试逻辑。

影响：网络已经恢复、连接器仍在线，但任务可能一直显示执行中，直到进程重启或人为重放。

建议：独立的持久化结果重试循环，带退避和抖动；将网络错误与永久业务拒绝分开，提供积压和最后回传错误的可见状态。

证据：[edge.py:388](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/fleet-edge/src/agentcenter_fleet/edge.py:388>)、[edge.py:557](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/fleet-edge/src/agentcenter_fleet/edge.py:557>)、[edge.py:589](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/fleet-edge/src/agentcenter_fleet/edge.py:589>)。

验收：仅让第一次回传失败，恢复网络后不重启连接器，任务自动结束；重放结果不会覆盖其他 attempt 或已确定的最终状态。

## 后续改进

1. **默认鉴权码。** 配置为空时回落到源码中的固定值。未检查用户实际 `.env`，不能断言当前部署仍使用默认值。对外部署应要求首次设置或生成实例独有凭据，并支持会话过期与撤销。证据：[config.py:29](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/backend/app/config.py:29>)。
2. **确认规则与生命周期文档漂移。** README 写“建任务先确认”“关窗即停”；当前代码直接派发，桌面 Rust 明确关窗不停止后台服务；架构文档内部也保留相反表述。需要明确写操作策略，并让文档、界面和契约测试保持一致。证据：[super_ai.py:345](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/backend/app/core/super_ai.py:345>)、[main.rs:1](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/desktop/src-tauri/src/main.rs:1>)。
3. **发布验证不足。** 未发现仓库内 CI 工作流和前端自动化测试；构建配置忽略 lint，eslint 配置引用的包未出现在 package.json 的直接依赖。Python 依赖主要只有下界，没有锁定测试环境。一次隔离测试因旧 TestClient API 不兼容失败，改用较新框架后通过，说明测试工具版本也需要纳入环境契约。证据：[next.config.ts:11](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/frontend/next.config.ts:11>)、[requirements.txt](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/backend/requirements.txt>)。
4. **产品范围应收敛。** 任务、项目、SOP、小队、Swarm、Autopilot、知识、技能、输出物、语音、桌面和固件并行推进，增加状态和维护成本。建议先把“派发→执行→看到结果→失败可恢复”作为主流程；其余能力按真实使用频率排序。
5. **检索与语音需要明确体验边界。** 默认向量是 256 维词元哈希，并非模型语义表示；连续中文会形成较长词元，需要用真实中文问题验证召回。浏览器不支持识别时，当前发送固定示例句，建议正式模式明确转为文字输入，示例只留在演示模式。证据：[text_embed.py:16](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/backend/app/core/text_embed.py:16>)、[super-ai-page.tsx:326](</Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/AgentCenter/frontend/src/components/super-ai/super-ai-page.tsx:326>)。
6. **维护边界。** `fleet.py` 1,851 行、`knowledge.py` 1,097 行、`super_ai.py` 1,059 行。建议沿认证、目录、调度、传输、结果归并等职责逐步拆分，以便为权限和故障路径建立独立测试。当前默认并发为 3，锁与信号量在进程内；没有压力测试证据支撑更大并发或多进程调度承诺。

## 建议推进顺序与验收

- **第一步：统一安全边界。** 修复 F1/F2/F3、移除固定默认入口凭据，增加身份×接口×任务归属的拒绝用例。所有 P0 复现应转成回归测试。
- **第二步：做完整可靠路径。** 先修 F5，再明确 v1/v2 迁移路径并补齐 F4；覆盖断网、重启、取消与完成竞态、重复投递和不同 attempt 的结果。
- **第三步：固定可发布基线。** 固定依赖和工具环境，运行后端测试、前端类型检查与构建、桌面打包冒烟；增加双运行时和双设备的最小端到端流程，并更新 README。
- **第四步：用真实任务决定扩展。** 小范围记录任务完成率、人工介入率、结果回传延迟、恢复耗时、每周重复使用人数和最常用入口，再决定语音、固件和更多编排界面的投入。当前没有这些数据，不能据代码推断商业验证或用户留存。

## 本次验证与边界

- 最终隔离环境运行现有测试：**123/123 通过**。Python 3.11.15、pytest 9.1.1，使用本机缓存依赖（FastAPI 0.133.1、Starlette 1.0.0、SQLAlchemy 2.0.50、Pydantic 2.12.5）；不是对仓库原有虚拟环境的可复现安装认证。
- 初次隔离运行 121/123 通过：一项因评估使用的临时输出路径与测试硬编码的 `Documents/expe` 后缀不一致，一项因旧 TestClient 不支持测试所用参数。调整隔离路径和缓存框架组合后全通过，未修改任何项目代码或测试。
- 88 个后端及连接器 Python 源文件语法检查通过。
- 实际应用对象上的 HTTP/WS 隔离复现、临时数据库上的跨节点领取复现均成功；连接器暂时回传失败的结果留存已复现。
- 前端 TypeScript 类型检查通过（`tsc --noEmit --incremental false`，退出码 0）；未确认前端正式构建、桌面打包、真实双运行时、云端、实体设备或负载表现。
- 未启动现有服务，未派发真实 Agent 任务，未修改项目实现、配置或工作目录中的既有修改。未读取真实凭据，也未进行竞品和市场调研。

**决策建议：继续做，把下一轮里程碑定义为“可信地跑完一个跨设备任务并能从故障中恢复”。新增功能排在这个里程碑之后。**
