# SignalLens

SignalLens 是一个以“AI 阅读分诊”为核心的内容消费助手。第一阶段支持通过浏览器插件采集网页，后端完成快速分诊、内容分析和个人化阅读建议，Web 端展示 Inbox 与章节级阅读计划。

## 目录

```text
apps/
├─ api/        FastAPI API 与独立 Worker 入口
├─ extension/  从 PageSift 提取核心派生的 Manifest V3 插件
└─ web/        Vue 3 Web 应用
deploy/         容器与反向代理配置
data/           本地 SQLite 数据（不提交）
docs/           产品与技术文档
```

## 本地开发

前端和插件：

```powershell
npm install
npm run typecheck
npm run build
npm run dev --workspace @signallens/web
```

后端：

```powershell
Copy-Item .env.example .env
uv sync --project apps/api
uv run --project apps/api signallens-api
```

另开终端启动 Worker：

```powershell
uv run --project apps/api signallens-worker
```

默认地址：Web `http://localhost:5173`，API 文档 `http://localhost:8000/docs`。

## 当前边界

- 当前提交建立可运行工程和采集任务骨架，尚未实现三阶段 LLM Prompt。
- 插件只允许向 SignalLens API 提交，不包含旧系统登录、收藏、图片上传或旧接口。
- Docker 配置已预留；本机需要先安装 Docker Desktop 才能运行容器验证。

