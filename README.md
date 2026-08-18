# SignalLens

SignalLens 是一个以"AI 阅读分诊"为核心的内容消费助手。它回答的不是"这篇内容能不能被总结"，而是：

- 这篇内容**是否值得占用注意力**；
- 摘要是否已经足够，还是需要精读原文；
- 哪些章节值得浏览、哪些值得深入；
- 哪些内容虽然不符合当前兴趣画像，但具有**认知探索价值**。

## 工作方式

浏览器插件提取网页正文并提交到本地后端，后端完成去重与持久化后创建分析任务。配置 OpenAI-compatible 模型后，Worker 依次执行快速分诊、内容分析和个性化评估三个阶段，最终在 Web 端呈现 Inbox、阅读建议和原始 Markdown。

详细产品方案见 [AI 内容筛选与消费助手 V0.3](docs/AI内容筛选与消费助手_V0.3_防信息茧房与认知多样性方案.md)，文档索引见 [docs/README.md](docs/README.md)。

## 系统架构

```text
网页
  ↓
SignalLens Extension（PageSift 提取核心）
  ↓  signallens.capture.v1
FastAPI
  ├─ auth / admin_users / plugin_api_key
  ├─ contents / content_revisions / content_claims
  ├─ analyses / analysis_jobs / cognitive_compare_runs
  ├─ cognitive_memories / memory_revisions / confirmation_events / proposals
  ├─ current_user_state / snapshots / claim_feedback / claim_corrections
  ↓
Analysis Worker（Triage → Analyze → Claims 持久化 → Memory 召回 → Compare → Evaluate）
  ↓
Vue Web：Inbox / 内容详情（认知差异）/ 偏好 / 当前状态 / 认知记忆 / 校准统计
```

## 当前能力

| 模块           | 已实现                                                       | 待实现                    |
| -------------- | ------------------------------------------------------------ | ------------------------- |
| **浏览器插件** | Key 配置、正文提取（选区/区域/整页）、质量判断、Markdown/JSON 导出、鉴权提交 | 分析结果摘要展示          |
| **后端 API**   | 单用户登录与改密、可撤销会话、最小权限插件 Key、内容采集与去重、分析状态管理、每日整理时段与立即整理、英文翻译任务、显式用户画像、人工反馈快照、校准统计、认知记忆管理与修改建议、当前阅读状态、Claim 级知晓/立场确认、认知关系与角色纠错 | 画像修改建议、Prompt 自提升 |
| **数据层**     | SQLite WAL 模式、内容/分析/翻译任务持久化、正文 Revision 与行级 Claims、append-only Memory Revision、Confirmation Event、Compare Run 快照、重复数据迁移 | 正式 Alembic 迁移体系     |
| **Worker**     | OpenAI/DeepSeek JSON 适配、截断精简重试、原子任务领取、低价时段调度、六阶段分析（含 Claims 持久化、Memory 候选召回与认知比较）、Compare 单独重试、Markdown 分块翻译与断点续跑、失败隔离、模型调用前生成来源章节清单 | 任务级退避重试、超时恢复  |
| **Web**        | 登录改密、Key 管理、整理时段开关、Inbox 分类（用户修正优先 + 简短 Delta 摘要）、阅读建议、Markdown 阅读/源码视图、中英对照、初始问卷、评测开关、阅读后反馈、四级校准矩阵、规则候选确认、顺序式引导阅读流、认知差异分区展示（已知/新增/扩展/冲突/更新）、折叠高级纠错、认知记忆管理页、当前阅读状态页 | 忽略内容抽检、Delta 差异整理 |
| **部署**       | Dockerfile、Compose、Nginx 示例                              | 容器实机验证              |

## 仓库结构

```text
SignalLens/
├─ apps/
│  ├─ api/          FastAPI + SQLAlchemy + Worker
│  ├─ extension/    Manifest V3 浏览器插件
│  └─ web/          Vue 3 前端
├─ data/            本地 SQLite（不入 Git）
├─ deploy/          Nginx 示例配置
├─ docs/            产品方案与项目文档
├─ compose.yaml     容器编排
├─ AGENTS.md        开发与协作规范
└─ package.json     npm workspace 入口
```

## 环境要求

| 依赖                             | 版本                 |
| -------------------------------- | -------------------- |
| Node.js                          | ≥ 22.12.0            |
| Python                           | ≥ 3.11               |
| [uv](https://docs.astral.sh/uv/) | 最新                 |
| Chrome / Edge                    | 用于加载开发版插件   |
| Docker Desktop                   | 仅验证容器部署时需要 |

## 快速开始

### 安装依赖

```bash
cd SignalLens
npm install
uv sync --project apps/api --extra dev
cp .env.example .env
```

### 配置 LLM（可选）

`.env` 中的 LLM 配置可以留空——未配置时 Worker 不消费任务，不会产生费用。需要分析功能时填写：

```dotenv
SIGNALLENS_LLM_BASE_URL=https://api.openai.com/v1
SIGNALLENS_LLM_API_KEY=你的密钥
SIGNALLENS_LLM_MODEL=支持结构化输出的模型名称
SIGNALLENS_LLM_RESPONSE_FORMAT=auto
SIGNALLENS_LLM_MAX_TOKENS=16384
```

> **关于 `RESPONSE_FORMAT`**：`auto` 会为 `api.deepseek.com` 使用 `json_object`，其他服务默认使用严格 `json_schema`。通过自建代理连接 DeepSeek 时可显式设为 `json_object`。两种模式的返回都经过 Pydantic 校验；遇到截断或无效 JSON 时自动精简重试。

### 启动后端

```bash
uv run --project apps/api signallens-api
```

- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>

首次启动自动创建 `admin` 账户，随机密码写入 `data/initial-admin-password.txt`（详见下方「安全模型」一节）。修改后端代码后需手动重启。

### 启动 Web

```bash
npm run dev --workspace @signallens/web
```

打开 <http://localhost:5173>，使用 `admin` 和初始密码登录。右上角出现"API 已连接"表示前后端连通。

### 构建并加载插件

```bash
npm run build --workspace @signallens/extension
```

在浏览器 `edge://extensions` 或 `chrome://extensions` 中开启开发人员模式，加载 `apps/extension` 目录即可。

### 启动 Worker

```bash
uv run --project apps/api signallens-worker
```

Worker 按创建时间领取任务，依次执行 Triage → Analyze → Evaluate 三阶段。

### 测试网页导入

1. 打开一篇文章页面；
2. 在 Web「账户安全」页生成插件 Key；
3. 打开 SignalLens 插件，粘贴 Key；
4. 检查提取质量后点击"提交 AI 分析"；
5. 返回 Inbox 查看结果。

## 安全模型

### 单用户设计

系统仅有唯一账户 `admin`，不提供注册接口。**不存在任何出厂默认口令。**

### 初始密码

- 仅在首次启动且 `admin` 不存在时随机生成（`secrets.token_urlsafe(18)`，约 24 字符高熵）；
- 写入 `data/initial-admin-password.txt`（原子替换，权限 0600，Git 已忽略）；
- 数据库只保存 scrypt 哈希（16 字节盐 + 64 字节派生值）。

### 强制改密

初始账户带"必须改密"标记。登录后强制进入改密页，完成前无法访问其他功能。改密成功后同时：撤销全部 Web 会话、清除标记、删除初始密码文件。

### 会话与插件 Key

- Web 会话：`secrets.token_urlsafe(32)` Bearer Token，数据库仅存 SHA-256 摘要，支持服务端撤销，默认 30 天过期；
- 插件 Key：`sk-sl-` 前缀的独立凭据（同样只存哈希），仅允许调用 `POST /api/v1/captures`。

## API 概览

| 方法              | 路径                                   | 用途                     |
| ----------------- | -------------------------------------- | ------------------------ |
| `GET`             | `/api/v1/health`                       | 健康检查                 |
| `POST`            | `/api/v1/auth/login`                   | 登录                     |
| `GET`             | `/api/v1/auth/me`                      | 当前账户状态             |
| `POST`            | `/api/v1/auth/change-password`         | 修改密码（撤销全部会话） |
| `POST`            | `/api/v1/auth/logout`                  | 撤销当前会话             |
| `GET/POST/DELETE` | `/api/v1/plugin-key`                   | 插件 Key 管理            |
| `POST`            | `/api/v1/captures`                     | 提交内容采集             |
| `GET`             | `/api/v1/contents`                     | 内容列表（含分析状态）   |
| `GET`             | `/api/v1/contents/{id}`                | 内容详情与完整分析       |
| `POST`            | `/api/v1/contents/{id}/translation`    | 创建/重试翻译            |
| `GET`             | `/api/v1/analyses/{id}`                | 分析任务状态             |
| `POST`            | `/api/v1/analyses/{id}/run-now`        | 立即执行（绕过时段）     |
| `POST`            | `/api/v1/analyses/{id}/retry`          | 重试失败任务             |
| `GET/PUT`         | `/api/v1/analysis-schedule`            | 整理时段配置             |
| `GET/PUT`         | `/api/v1/profile`                      | 用户画像                 |
| `GET/PUT`         | `/api/v1/user-state`                   | 当前阅读状态             |
| `GET`             | `/api/v1/memory`                       | 认知记忆列表             |
| `GET`             | `/api/v1/memory/{id}`                  | 记忆版本历史与确认记录   |
| `POST`            | `/api/v1/memory`                       | 手工录入（先 Memory Match） |
| `POST`            | `/api/v1/memory/{id}/revisions`        | 追加不可变版本           |
| `GET`             | `/api/v1/memory/proposals`             | 待确认修改建议           |
| `POST`            | `/api/v1/memory/proposals/{id}/decision` | 接受/拒绝修改建议      |
| `GET`             | `/api/v1/analyses/{id}/compare`        | Compare 完整输入与结果   |
| `POST`            | `/api/v1/analyses/{id}/retry-compare`  | 单独重试 Compare         |
| `PUT`             | `/api/v1/analyses/{id}/feedback`       | 阅读后评价               |
| `POST`            | `/api/v1/analyses/{id}/claims/{claim_id}/feedback` | Claim 级知晓/立场确认 |
| `POST`            | `/api/v1/analyses/{id}/claims/{claim_id}/correction` | 关系/角色高级纠错 |
| `GET`             | `/api/v1/calibration/stats`            | 校准统计                 |
| `PUT`             | `/api/v1/calibration/suggestions/{id}` | 确认/拒绝规则候选        |

除健康检查和登录外，所有接口需要 `Authorization: Bearer <token>`。插件 Key 仅能调用 `POST /api/v1/captures`。

## 内容去重与时间规则

**去重**：内容身份由 `source_type + canonical_url` 决定。URL 会移除片段和常见追踪参数（`utm_*`、`from`、`ref` 等）。重复提交更新正文快照，复用已有记录。

**时间**：数据库存 UTC，API 返回带时区的时间，Web 统一显示北京时间（`Asia/Shanghai`）。

## Worker 行为说明

- **整理时段**：可配置低价时段窗口，正文入库不受影响，仅模型请求在窗口内发起。关闭总开关则提交后立即分析；
- **来源章节**：Worker 在调用模型前解析正文 H1～H3 并选择单一主章节层级（2～10 个标题），生成带行号引用的章节清单；正文在分析期间被重新采集时，任务从分诊阶段重新开始；
- **六阶段分析**：Triage → Analyze → Claims 持久化 → Memory 候选召回 → Cognitive Compare → Evaluate。正文变化创建新 Content Revision，旧 Claim 证据不被覆盖；旧分析保持 legacy，不伪造 Delta；
- **认知差异（Delta）**：Compare 只输出逐 Claim 的主关系与多 Memory 匹配证据，聚合统计与召回上下文状态由代码计算；`new` 只表示"本次可用、已确认且成功召回的认知记忆中没有对应项"；
- **认知记忆（Memory）**：具体内容只存在 append-only Revision 中；CREATE 前必须执行 Memory Match（文本完全匹配 → 复用 Delta → 实体/主题召回 → LLM 语义判断），等价且状态未变时只追加 Confirmation Event，不确定时生成待确认 Proposal；知晓状态与观点立场分开保存；
- **引导阅读流**：`selective_read` 的章节动作携带 `section_ref`，Web 按来源顺序原位展示摘要、折叠卡片与正文；译文完成后原文引导流不变，中英对照视图的左右两侧按同一章节清单标注动作；引用缺失、重复或正文哈希变化时整体退回完整原文，不展示部分引导流；
- **翻译**：用户主动触发，不受时段限制。按 Markdown 块分批翻译并保存进度，代码/图片/链接保持原样。正文变化后旧译文自动失效；
- **失败处理**：单任务失败标记为 `failed`，不终止 Worker，可在详情页重试；Compare 失败不阻塞分析（Evaluate 保守降级），可单独重试 Compare；
- **画像**：保存后用于后续新任务，不自动重算历史；`known_topics` 始终作为弱先验，不自动转换为已确认记忆；
- **校准**：累计 ≥ 20 条有效反馈后提出规则候选，接受仅记录决定，不自动修改 Prompt 或画像。

## 测试与构建

```bash
# 前端
npm run typecheck
npm test
npm run build

# 后端
cd apps/api
uv run pytest
uv run ruff check src tests
```

## 生产部署

生产环境示例（替换为你的实际域名）：

```text
Web + API：https://lens.example.com
API 前缀：https://lens.example.com/api/v1
```

必须通过 HTTPS 暴露服务，不能将 8000 端口直接开放公网。登录限流应在 Nginx 层配置。`deploy/` 目前为 HTTP 示例，部署前需完成证书配置。

Docker 部署时读取初始密码：

```bash
docker compose exec api cat /data/initial-admin-password.txt
```

插件生产构建：

```bash
SIGNALLENS_EXTENSION_API_BASE_URL="https://lens.your-domain.com/api/v1" \
SIGNALLENS_EXTENSION_WEB_BASE_URL="https://lens.your-domain.com" \
npm run build --workspace @signallens/extension
```

> 注意：需同步将 `manifest.json` 中的 `host_permissions` 更新为实际域名。

## 路线图

Memory V1 主线（Claims 与来源基础 → Cognitive Memory 与确认机制 → Current User State → Cognitive Compare 与 Delta → Evaluate 接入与反馈闭环）已实现，下一步：

1. 持续积累人工反馈、Claim 级确认与高级纠错 Ground Truth；
2. 增加"AI 判断 vs 用户评价"差异整理（画像修改须用户确认）；
3. 增加被建议忽略内容的抽检，降低高价值误杀；
4. Prompt 自提升链路（版本快照 → 根因诊断 → 候选生成 → 影子验证与受控启用）；
5. 用户满意后关闭评测模式，保留反馈入口和历史数据。

暂不实现：PDF、音视频、RSS、RAG、向量数据库、知识图谱、复杂推荐算法、多用户、Prompt 自动启用。

## License

SignalLens 以 [Apache License 2.0](LICENSE) 开源。
