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
| 浏览器插件 | 插件 Key 配置、网页正文提取、选区/区域/整页提取、质量判断、Markdown/JSON 导出、鉴权提交 | 分析结果摘要 |
| 后端 API | 单用户登录与改密、可撤销 Web 会话、最小权限插件 Key、内容采集与去重、分析状态、每日 AI 整理时段与立即整理、英文正文翻译任务、显式用户画像、人工反馈快照、校准统计 | 画像修改建议 |
| 数据层 | SQLite、WAL、内容/分析/翻译任务持久化、已有重复数据迁移 | 正式 Alembic 迁移体系 |
| Worker | OpenAI/DeepSeek JSON 输出适配、JSON 截断精简重试、原子任务领取、按低价时段分阶段执行、三阶段分析、Markdown 分块翻译与断点续跑、失败隔离 | 任务级退避重试、超时任务恢复 |
| Web | 登录、改密、插件 Key 管理、AI 整理总开关与每日时段、等待任务立即整理、用户修正优先的 Inbox 分类、阅读建议、Markdown 阅读/源码视图、英文原文与中文译文对照、初始问卷、评测开关、阅读后反馈、四级校准矩阵和规则候选确认 | AI 案例级差异解释、忽略内容抽检 |
| 部署 | Dockerfile、Compose、Nginx 示例 | 当前开发机未安装 Docker，容器尚未实机验证 |

## 系统结构

```text
网页
  ↓
SignalLens Extension（PageSift 提取核心）
  ↓  signallens.capture.v1
FastAPI
  ├─ admin_users / auth_sessions / plugin_api_key
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
SIGNALLENS_LLM_RESPONSE_FORMAT=auto
SIGNALLENS_LLM_MAX_TOKENS=16384
```

`auto` 会为 `api.deepseek.com` 使用非思考模式的 `json_object`，其他服务默认使用严格 `json_schema`。如果通过自建代理连接 DeepSeek，可以显式设置 `SIGNALLENS_LLM_RESPONSE_FORMAT=json_object`。两种模式的返回结果都会经过同一套 Pydantic 契约校验；遇到截断或无效 JSON 时会自动用精简指令重试一次。

## 本地运行

### 1. 启动后端

```powershell
cd E:\Code\Git\SignalLens
uv run --project apps/api signallens-api
```

验证：

- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>

首次启动会创建唯一账户 `admin`，随机初始密码位于：

```text
data/initial-admin-password.txt
```

该文件已被 Git 忽略。使用初始密码登录 Web 后会进入“账户安全”页；修改密码成功会撤销全部 Web 会话，并自动删除该初始密码文件。插件使用独立 Key，不保存 admin 密码。

修改后端代码后需要停止并重新启动，因为当前启动入口没有开启自动重载。

### 2. 启动 Web

另开一个终端：

```powershell
cd E:\Code\Git\SignalLens
npm run dev --workspace @signallens/web
```

打开 <http://localhost:5173>，使用 `admin` 和初始密码登录。页面右上角出现“API 已连接”表示本地前后端已连通。

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
2. 在 Web 的“账户安全”页生成并复制插件 Key；
3. 打开 SignalLens 插件，粘贴并保存 Key；
4. 检查标题、字数、提取质量和 Markdown 预览；
5. 点击“提交 AI 分析”，再返回 <http://localhost:5173/inbox>。

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
| `POST` | `/api/v1/auth/login` | 使用 admin 密码登录 |
| `GET` | `/api/v1/auth/me` | 获取当前登录账户状态 |
| `POST` | `/api/v1/auth/change-password` | 修改密码并撤销全部 Web 会话 |
| `POST` | `/api/v1/auth/logout` | 撤销当前设备会话 |
| `GET` | `/api/v1/plugin-key` | 获取插件 Key 的非敏感状态 |
| `POST` | `/api/v1/plugin-key` | 生成并替换唯一插件 Key |
| `DELETE` | `/api/v1/plugin-key` | 撤销插件 Key |
| `POST` | `/api/v1/captures` | 保存或更新一次内容采集 |
| `GET` | `/api/v1/contents` | 获取最近内容及最新分析状态 |
| `GET` | `/api/v1/contents/{content_id}` | 获取 Markdown 和完整分析字段 |
| `POST` | `/api/v1/contents/{content_id}/translation` | 幂等创建或重试英文正文翻译 |
| `GET` | `/api/v1/analyses/{analysis_id}` | 查询分析任务状态 |
| `POST` | `/api/v1/analyses/{analysis_id}/run-now` | 让等待任务绕过整理时段立即执行 |
| `POST` | `/api/v1/analyses/{analysis_id}/retry` | 重新执行失败的分析任务 |
| `GET` | `/api/v1/analysis-schedule` | 获取 AI 整理总开关、时段和队列状态 |
| `PUT` | `/api/v1/analysis-schedule` | 保存 AI 整理总开关和每日时段 |
| `GET` | `/api/v1/profile` | 获取初始问卷和评测模式 |
| `PUT` | `/api/v1/profile` | 保存显式用户画像 |
| `PUT` | `/api/v1/analyses/{analysis_id}/feedback` | 新增或更新阅读后评价 |
| `GET` | `/api/v1/calibration/stats` | 获取推荐偏差和摘要问题统计 |
| `PUT` | `/api/v1/calibration/suggestions/{suggestion_id}` | 接受或拒绝下一版阅读规则候选 |

除健康检查和登录外，所有 `/api/v1` 接口都必须发送 `Authorization: Bearer <token>`。Web 使用登录会话；插件使用形如 `sk-sl-...` 的独立 Key，而且该 Key 只允许调用 `POST /api/v1/captures`。重新生成 Key 会立即使旧值失效，数据库仅保存哈希。Docker 部署时初始密码位于 API 容器挂载卷的 `/data/initial-admin-password.txt`，可用以下命令读取：

```bash
docker compose exec api cat /data/initial-admin-password.txt
```

生产环境必须通过 HTTPS 暴露 Web/API，不能把 API 的 `8000` 端口直接开放到公网；登录接口的限流应在正式 Nginx 配置中启用。当前 `deploy/` 仍是 HTTP 示例，部署前需要完成证书和限流配置。

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

“整理设置”页可以开启低价时段模式并配置一个或多个北京时间窗口。文章正文仍会在插件提交后立即可靠入库；Worker 只在允许窗口内发起每个分析阶段的模型请求。窗口关闭时已完成阶段会保留到下一窗口，用户也可以在内容详情页明确选择“立即整理”。关闭总开关会恢复提交后立即分析；若当前有等待任务，Web 会先提示这些任务可能在高价时段开始执行。正文翻译是单独的用户主动操作，不受整理时段限制。

模型输出必须通过 Pydantic/JSON Schema 校验。单条任务失败会标记为 `failed`，不会丢失原始正文，也不会终止 Worker；内容详情页可以将失败任务重新放回队列。手动提交的有效内容不会被快速分诊静默拦截。

英文正文可在详情页按需点击“翻译为中文”。翻译不会覆盖原始 Markdown，也不会自动产生模型费用；Worker 按 Markdown 内容块分批翻译并保存进度，代码、图片和链接地址保持原样。重复点击复用当前正文快照的译文，正文重新采集发生变化后旧译文自动失效。桌面端按内容块左右对照，窄屏按原文、译文上下排列；图片或图表内部文字暂不翻译。

阅读偏好页保存后，Worker 会将显式画像用于后续新领取任务的 `TriageContent` 和 `EvaluateForUser`。系统不会自动重算历史文章，也不会根据单篇反馈自动修改画像。阅读后评价会冻结当时的模型、Prompt 版本和三阶段结果，供后续公平比较。

用户提交明确阅读等级后，Inbox 以用户修正等级作为最终分类，同时保留 AI 原始建议用于评测。累计至少 20 条包含明确等级的有效反馈后，统计页才会根据重复偏差提出下一版阅读规则候选；接受候选只记录人工决定，不会自动训练模型、修改画像或直接改写当前 Prompt。

## 下一阶段

下一阶段按以下顺序推进：

1. 在真实阅读中持续积累人工反馈和 AI 结果快照；
2. 增加“AI 判断 vs 用户评价”的差异整理，但画像修改必须由用户确认；
3. 增加被建议忽略内容的少量抽检，降低高价值误杀的幸存者偏差；
4. 根据校准统计调整 Prompt 并提升版本；
5. 用户满意后关闭评测模式，继续保留普通反馈入口和历史回归数据。

V0.1 暂不实现 PDF、音视频、RSS、RAG、向量数据库、知识图谱和复杂推荐算法。
