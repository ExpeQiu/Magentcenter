# ADR-002：桌面端改为 Tauri 2 + 静态前端 + FastAPI sidecar

- 状态：已采纳
- 日期：2026-08-25

## 决策

桌面安装包使用 **Tauri 2 官方 DMG**，一个原生窗口：

1. 前端 `next build` 使用 `output: 'export'`，产物为静态 HTML/CSS/JS，运行时不再内嵌 Node。
2. FastAPI 作为 sidecar（便携 CPython + uvicorn），同时提供 `/api` 与静态页；窗口加载 `http://127.0.0.1:8013/`。
3. 关闭窗口 / 退出应用时结束 sidecar 进程组，避免 API 残留。
4. 包内只带 `.env.example`。真实密钥写在安装后的 `~/Library/Application Support/AgentCenter/.env`。

## 为何不用 Electron

Electron 需要随包 Node 跑 Next standalone，体积大、关窗后进程易残留，且与「静态页 + sidecar」模型不符。

## 详情路由

静态导出无法为每个 task/session id 预渲染。详情改为 query：`/{slug}/tasks/detail?id=`。旧路径由 FastAPI 302。
