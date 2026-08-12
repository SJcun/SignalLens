# SignalLens

SignalLens 是一个以“AI 阅读分诊”为核心的内容消费助手。它希望回答的不是“这篇内容能不能被总结”，而是：

- 这篇内容是否值得占用注意力；
- 摘要是否已经足够；
- 哪些章节值得浏览或精读；
- 哪些内容虽然不符合当前兴趣画像，但具有认知探索价值。

项目当前已经打通基础闭环：浏览器插件可以提取网页并提交到本地后端，后端可以去重、持久化并创建分析任务；配置 OpenAI-compatible 模型后，Worker 会执行快速分诊、内容分析和个性化评估，Web 可以展示 Inbox、阅读建议和原始 Markdown。

详细产品方案见 [AI 内容筛选与消费助手 V0.3](docs/AI内容筛选与消费助手_V0.3_防信息茧房与认知多样性方案.md)，文档索引见 [docs/README.md](docs/README.md)。

## 当前能力

| 模块 | 已实现 | 尚未实现 |
| --- | --- | --- |
| 浏览器插件 | 网页正文提取、选区/区域/整页提取、质量判断、Markdown/JSON 导出、提交本地后端 | 插件 Token、分析结果摘要 |
| 后端 API | 健康检查、内容采集、URL 去重、内容列表、内容详情、分析状态查询、结构化结果校验 | 用户鉴权、反馈、画像、统计接口 |
| 数据层 | SQLite、WAL、内容/分析/任务持久化、已有重复数据迁移 | 正式 Alembic 迁移体系 |
| Worker | OpenAI-compatible Provider、原子任务领取、三阶段分析、逐阶段持久化、失败隔离 | 自动重试、超时任务恢复、人工重跑 |
| Web | Inbox、分析状态轮询、阅读建议、摘要、关键点、阅读计划和原始 Markdown | 偏好编辑、反馈和统计数据 |
| 部署 | Dockerfile、Compose、Nginx 示例 | 当前开发机未安装 Docker，容器尚未实机验证 |

## 系统结构

```text
网页
  ↓
SignalLens Extension（PageSift 提取核心）
  ↓  signallens.capture.v1
FastAPI
  ├─ contents
  ├─ analyses
  └─ analysis_jobs
       ↓
Analysis Worker（Triage → Analyze → Evaluate）
       ↓
Vue Web：Inbox / 内容详情 / 偏好 / 统计
```

生产环境预定使用：

```text
Web：https://lens.example.com
API：https://lens.example.com/api/v1
```

新系统与旧系统共享根域名，但代码、数据库、接口和插件数据通道相互独立。插件中不得重新加入旧域名、旧账户、Memento 收藏或旧 `/plugin-*` 接口。

## 仓库结构

```text
SignalLens/
├─ apps/
│  ├─ api/        FastAPI、SQLAlchemy、SQLite 和 Worker
│  ├─ extension/  Manifest V3 浏览器插件
│  └─ web/        Vue 3 Web 应用
├─ data/           本地 SQLite 数据和备份，不提交 Git
├─ deploy/         Nginx 示例配置
├─ docs/           产品方案和项目文档体系
├─ compose.yaml    API、Worker、Web 容器编排
├─ AGENTS.md       仓库开发与协作规范
└─ package.json    Web 与插件的 npm workspace 入口
```

## 环境要求

- Node.js `>= 22.12.0`
- npm
- Python `>= 3.11`
- [uv](https://docs.astral.sh/uv/)
- Chrome 或 Edge，用于加载开发版插件
- Docker Desktop，仅在需要验证容器部署时安装

## 首次安装

在仓库根目录执行：

```powershell
cd E:\Code\Git\SignalLens
npm install
uv sync --project apps/api --extra dev
Copy-Item .env.example .env
```

`.env` 中的 LLM 配置可以留空。未配置模型时 Worker 不消费任务，也不会生成伪分析结果。需要分析时填写：

```dotenv
SIGNALLENS_LLM_BASE_URL=https://api.openai.com/v1
SIGNALLENS_LLM_API_KEY=你的密钥
SIGNALLENS_LLM_MODEL=支持结构化输出的模型名称
```

当前 Provider 使用 OpenAI Chat Completions 的 `json_schema` 结构化输出。其他兼容服务必须同时支持该请求格式。

## 本地运行

### 1. 启动后端

```powershell
cd E:\Code\Git\SignalLens
uv run --project apps/api signallens-api
```

验证：

- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>

修改后端代码后需要停止并重新启动，因为当前启动入口没有开启自动重载。

### 2. 启动 Web

另开一个终端：

```powershell
cd E:\Code\Git\SignalLens
npm run dev --workspace @signallens/web
```

打开 <http://localhost:5173/inbox>。页面右上角出现“API 已连接”表示本地前后端已连通。

### 3. 构建并加载插件

开发构建默认连接本地 API 和本地 Web：

```powershell
cd E:\Code\Git\SignalLens
npm run build --workspace @signallens/extension
```

在浏览器中：

1. 打开 `edge://extensions` 或 `chrome://extensions`；
2. 开启开发人员模式；
3. 点击“加载解压缩的扩展”；
4. 选择 `E:\Code\Git\SignalLens\apps\extension`；
5. 插件重新构建后，在扩展管理页点击“重新加载”。

若要生成生产地址构建：

```powershell
$env:SIGNALLENS_EXTENSION_API_BASE_URL="https://lens.example.com/api/v1"
$env:SIGNALLENS_EXTENSION_WEB_BASE_URL="https://lens.example.com"
npm run build --workspace @signallens/extension
```

### 4. 测试网页导入

保持本地后端和 Web 运行：

1. 打开一篇普通 HTTP/HTTPS 文章；
2. 打开 SignalLens 插件；
3. 检查标题、字数、提取质量和 Markdown 预览；
4. 点击“提交 AI 分析”；
5. 返回 <http://localhost:5173/inbox>。

Inbox 最迟约 5 秒自动刷新，也可以手动刷新页面。点击内容卡片可以查看原网页入口和提取后的完整 Markdown。

未启动 Worker 或未配置模型时，预期状态是“等待分析”。配置模型并启动 Worker 后，页面会从“等待分析”切换为“分析中”，完成后展示阅读建议和结构化结果。

## 内容身份与时间规则

同一文章重复提交不会产生多条内容：

- 内容身份由 `source_type + canonical_url` 决定；
- URL 会移除片段、`utm_*`、`from`、`entry`、`ref` 等常见追踪参数；
- 重复提交会更新正文快照，并复用已有内容和分析记录；
- `capture_id` 只标识一次采集请求，不代表内容身份。

时间处理规则：

- 数据库存储 UTC；
- API 返回带 `Z` 或 UTC offset 的时间；
- Web 固定使用 `Asia/Shanghai` 显示北京时间；
- 不允许在数据库中直接保存没有语义说明的本地时间。

本地数据库默认位于：

```text
data/signallens.db
```

## 当前 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/v1/health` | 健康检查 |
| `POST` | `/api/v1/captures` | 保存或更新一次内容采集 |
| `GET` | `/api/v1/contents` | 获取最近内容及最新分析状态 |
| `GET` | `/api/v1/contents/{content_id}` | 获取 Markdown 和完整分析字段 |
| `GET` | `/api/v1/analyses/{analysis_id}` | 查询分析任务状态 |

## 测试与构建

Web 和插件：

```powershell
npm run typecheck
npm test
npm run build
```

后端：

```powershell
Push-Location apps/api
uv run pytest
uv run ruff check src tests
Pop-Location
```

说明：插件的 Defuddle 回归测试在 jsdom 中可能输出选择器兼容错误日志；只要最终测试断言全部通过，就不代表真实浏览器提取失败。

## Worker

配置模型后，在另一个终端启动 Worker：

```powershell
uv run --project apps/api signallens-worker
```

Worker 会按创建时间领取待处理任务，并依次执行：

1. `TriageContent`：快速判断内容信号和探索价值；
2. `AnalyzeContent`：只分析文章本身，保留反方观点、限制和未验证主张；
3. `EvaluateForUser`：生成阅读动作和阅读计划。

模型输出必须通过 Pydantic/JSON Schema 校验。单条任务失败会标记为 `failed`，不会丢失原始正文，也不会终止 Worker。手动提交的有效内容不会被快速分诊静默拦截。偏好持久化尚未实现，因此当前 `EvaluateForUser` 使用空画像做保守评估，不能视为已经完成真正的个性化。

## 下一阶段

下一阶段按以下顺序推进：

1. 建立 25～40 篇真实文章评测集；
2. 人工验证低相关高价值内容、知识点新颖性和观点保真度；
3. 根据评测结果调整 Prompt 并提升 Prompt 版本；
4. 实现偏好编辑和用户画像持久化，使 `EvaluateForUser` 真正个性化；
5. 增加失败任务重跑、反馈和统计闭环。

V0.1 暂不实现 PDF、音视频、RSS、RAG、向量数据库、知识图谱和复杂推荐算法。
