# 微雪 ESP32-S3-Touch-LCD-1.85C V2 直连 AgentCenter

目标：保留小智语音、屏幕、唤醒能力；ESP32 自身通过 HTTP 请求 http://47.113.225.93:8080，不依赖 Mac 上的桥接服务。

基于小智官方 v2.4.0，新增构建变体 esp32-s3-touch-lcd-1.85c-agentcenter-v2。使用 V2 的 ES8311/ES7210 音频配置。设备端工具 self.agentcenter.ask 和 self.agentcenter.task 分别请求 /api/super-ai/device/turn 与 /api/super-ai/device/tasks/{id}。

网络调用使用独立、最多一个并发请求的工作任务，结果发回小智供语音播报，也显示在屏幕。云端待确认操作只随用户的下一次请求回传，不自动确认。首次启动将已绑定的设备令牌存入独立 NVS namespace agentcenter。私密凭证头文件与固件二进制应仅用于本机设备，不可公开分享。

普通语音对话仍依赖小智云端；超级AI接口请求由 ESP32 发起，无需 Mac。当前自定义变体暂停小智自动固件升级，以避免被标准固件覆盖。后续升级需显式重新构建和烧录。

恢复备份：原16MB固件保存在 AgentCenter/xiaozhi-bridge/backups/before-agentcenter-16mb.bin。完整烧录新镜像前应将原 NVS 区的网络配置和身份数据复制到新镜像中的 NVS 分区，再验证屏幕、唤醒、语音及直连接口。

构建：在 ESP-IDF 5.5.2 环境运行 python scripts/release.py waveshare/esp32-s3-touch-lcd-1.85c --name esp32-s3-touch-lcd-1.85c-agentcenter-v2。

初始构建脚本8项测试通过；编译与真机验证状态另见交付记录。

## 已完成验证

2026-10-14：固件 xiaozhi 2.4.0 自定义 V2 变体编译成功，应用占用 0x2b7f30 字节，应用分区尚余31%。MQTT 与 WebSocket 实现均编入本次构建。8项构建脚本测试与新增客户端格式检查通过。

完整镜像刷入后，esptool 数据哈希校验通过。原 NVS 分区0x9000/0x4000内容逐字节保留；启动后的设备 UUID 保持725c968a-ae9f-449d-bf2a-269a457c9cdc，Wi-Fi自动连接Cyber。

实机日志确认 ST77916 屏幕、ES8311/ES7210 音频、AEC/VAD/WakeNet“你好小智”已初始化，小智 MQTT 连接成功并进入idle。

停止本次安装的Mac MCP桥接后，ESP32启动任务直接请求/api/super-ai/device/turn，返回HTTP 200 / ESP_OK，以及“协调器正常，本机没有执行器”。这验证了无需Mac桥接的设备直连接口。语音识别后实际调用该工具及扬声器播报仍需用户在设备上验证。

## 使用

用独立USB电源供电并连接Cyber即可，不需要Mac运行桥接。
唤醒小智，说“调用超级AI，查询系统状态”。普通闲聊仍由小智云处理。超级AI派发实际执行任务，需要云端有已绑定、在线的执行器；当前服务报告没有执行器。

本次保留屏幕与音频功能，但未新增触摸驱动。修改的固件暂停自动上游OTA，避免设备端直连工具被标准固件替换。

## 恢复

恢复镜像pre-flash-16mb.bin为烧录前最新完整备份。可使用esptool对ESP32-S3在地址0x0写回该镜像；恢复将撤回本次直连固件。备份和固件均包含设备私密配置，不要公开分享。

source-without-credentials.tar.gz为不含私密凭证头文件的完整修改源码；重建需准备agentcenter_credentials.h，宏为AGENTCENTER_URL、AGENTCENTER_DEVICE_ID、AGENTCENTER_BOOTSTRAP_TOKEN。最终代码以源码归档为准。
