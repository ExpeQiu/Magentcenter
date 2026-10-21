# ESP32 设备端 AgentCenter 工具

硬件：微雪 ESP32-S3-Touch-LCD-1.85C V2。固件：小智 2.4.0 定制版本。
云端：http://47.113.225.93:8080，工作区：cyber。

## self.agentcenter.ask

用途：向超级AI提问或提交用户请求。
参数：text（必填字符串，用户原始请求）。
请求：POST /api/super-ai/device/turn，使用 X-Device-Token 认证。
返回：云端 JSON，包含 reply，以及可能出现的 task_id、pending、confirmation_id 等信息。回复同时送到设备屏幕，并作为工具结果交给小智处理播报。
需要确认的操作不会自动确认；下一次用户请求会带回之前的确认信息。
语音示例：“调用超级AI，查询系统状态。”

## self.agentcenter.task

用途：查询超级AI任务的进度和结果。
参数：task_id（可选字符串；留空查询最近一次请求返回的任务）。
请求：GET /api/super-ai/device/tasks/{task_id}，使用 X-Device-Token 认证。
返回：任务 JSON，包含 reply、status、done 等信息。
语音示例：“查询刚才超级AI任务的进度。”

## 实现和构建

agentcenter_direct.cc / agentcenter_direct.h 是这两个工具的实现文件。网络请求由独立工作任务执行，避免阻塞小智的音频和界面。
它们依赖定制固件内的后台 MCP 调度、CONFIG_AGENTCENTER_DIRECT、esp_http_client，以及私有 agentcenter_credentials.h；单独复制这两个文件到标准小智固件不足以直接编译。
完整配套源码在 source-without-credentials.tar.gz 中，构建和恢复方法见 README.md。私密凭证头文件未复制到此目录。

已实机验证 ESP32 直接请求云端返回 HTTP 200，Mac 桥接已停止。小智唤醒、语音识别和生成回复已在日志中观察到；完整超级AI工具调用及实际播报仍需要进一步实测。
云端当前没有执行器，执行任务需要先绑定在线智能体。
