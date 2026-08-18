---
title: 002 实现记录：Memory V1 主线（M0～M3）
version: v1.0
status: 进行中
date: 2026-08-18
---

# 002 实现记录：Memory V1 主线（M0～M3）

本文记录 [002_SignalLens下一阶段升级方案](./002_SignalLens下一阶段升级方案.md) 第一批实施任务（Memory V1 主线 M0～M3）的实际修改范围。执行状态：Memory 主线已完成；O0～O2（Prompt 自提升）未开始。

## 1. 修改范围总览

| 层次 | 新增 | 修改 |
| --- | --- | --- |
| 数据层 | `content_revisions`、`content_claims`、`cognitive_memories`、`cognitive_memory_revisions`、`cognitive_memory_evidence`、`memory_confirmation_events`、`memory_change_proposals`、`current_user_state`、`current_user_state_snapshots`、`cognitive_compare_runs`、`claim_feedback_events`、`claim_corrections` 共 12 张新表 | `analyses` 增加 4 个关联列；`create_schema` 迁移注册与补列 |
| 分析契约 | `ContentClaim` 扩展、`CognitiveCompare` 系列 Schema、`CurrentUserState`、Memory Match 判断 Schema | `TriageContent`/`AnalyzeContent`/`EvaluateForUser` 不变；Evaluate Prompt v0.7.0 |
| 服务层 | `analysis/claims.py`、`analysis/compare.py`、`analysis/retrieval.py`、`memory.py` | `analysis/pipeline.py`、`analysis/prompts.py`、`analysis/provider.py` |
| Worker | `persist_claims`、`retrieve_memory`、`compare` 三个新阶段（共六阶段） | 任务流转、Evaluate 输入、正文 Revision 创建 |
| API | Memory 管理、Proposal 决策、当前状态、Compare 诊断与重试、Claim 反馈、Claim 纠错 | 详情/列表返回 Claims、Delta 与简短摘要；队列阶段枚举扩展 |
| Web | `CognitiveDeltaSection.vue`、`MemoryView.vue`、`UserStateView.vue`，路由与导航 | `api.ts` 类型与函数、详情页、Inbox 摘要、测试 mock |

## 2. 数据模型变更

### 2.1 Content Revision 与 Claims

- `content_revisions`：正文的不可变快照，`(content_id, version)` 唯一；同一正文哈希复用同一 Revision，正文变化创建新版本；
- `content_claims`：行级主张，`(analysis_id, claim_id)` 唯一；系统持久化时分配 `claim-001` 形式 ID，写回 `content_analysis_json` 供 Compare/Evaluate 引用；
- `analyses` 新增：`content_revision_id`、`current_user_state_snapshot_id`、`cognitive_compare_run_id`、`retrieval_context_status`。

旧分析（升级前创建）保持 legacy：不创建 Revision、不回填行级 Claims，仍可完整读取旧 JSON 结果，不进入正式 Compare。

### 2.2 Cognitive Memory 五张表

- `cognitive_memories`：逻辑身份 + `current_revision_id` 指针；
- `cognitive_memory_revisions`：append-only，`(cognitive_memory_id, version)` 唯一，保存 `awareness_state`（known/uncertain）、`stance`（accept/reject/mixed/undecided/not_applicable）、`lifecycle`（active/obsolete）、`confidence`、`source_type`（manual/claim_feedback/accepted_proposal）——三个维度分列保存，"知道但反对"合法；
- `cognitive_memory_evidence`：Revision 与来源 Claim 的显式关联，`(revision_id, claim_id, evidence_role)` 唯一；
- `memory_confirmation_events`：append-only 确认记录，`observed_revision_id` 固定指向确认时看到的当前版本；
- `memory_change_proposals`：未确认修改建议，`action` 五种（CREATE/REVISE/MARK_OBSOLETE/REACTIVATE/RESOLVE_MATCH），`status` 四种（pending/accepted/rejected/stale）。

### 2.3 Current User State

- `current_user_state`：单用户一行（`id = "default"`），与长期画像分离，`valid_until` 过期后按未设置处理；
- `current_user_state_snapshots`：Evaluate 前冻结的不可变快照，暂停续跑时复用，用户后续修改不重写历史分析。

### 2.4 Compare 与反馈

- `cognitive_compare_runs`：保存 Claim ID 集合、current/historical 两组候选 Revision ID（不是 Memory ID 或版本数字）、代码计算的召回上下文、模型输出与派生摘要、状态与错误；
- `claim_feedback_events`：Claim 级知晓/立场确认记录（含根因分流）；
- `claim_corrections`：primary_relation / claim_role 纠错，原始值与纠正值都保留。

## 3. 服务逻辑

### 3.1 Claims 持久化（analysis/claims.py）

- `with_normalized_claims`：旧格式 Claims 补缺省字段（claim_type=interpretation、claim_role=detail 等保守默认），使升级前分析可继续被新 Schema 解析；
- `persist_claims`：分配稳定 claim_id、幂等（重复运行不重复插入）、section_ref 不在系统章节清单中时置空而不是伪造；
- `ensure_content_revision`：按 `(content_id, source_hash)` 幂等创建 Revision。

### 3.2 Memory Match（memory.py）

CREATE 前匹配顺序：规范化文本完全匹配 → 复用当前 Cognitive Delta 的 matches → 实体/主题召回 → LLM 语义判断。

- 只有确定性完全匹配或 `confidence = high` 的语义判断才自动采用 equivalent/different；模型失败、结构无效、置信不足、引用未检查 Revision 一律降级 `uncertain`；
- 无候选且召回流程正常时视为 `different`（"相对已记录认知无对应项"），不断言用户现实中不知道；
- 结果处理：equivalent + 状态未变 → 只追加 Confirmation Event 与 Evidence；equivalent + 变化 → 原子追加 Revision；different → 新建 Memory + v1；uncertain → RESOLVE_MATCH Proposal；
- Proposal 接受前校验 `expected_current_revision_id`，指针已变化标记 stale 并返回冲突；RESOLVE_MATCH 合并时校验候选仍是该 Memory 当前版本；
- 用户未表态立场时（仅确认知晓），目标 stance 保留原值不重置。

### 3.3 候选召回与检索上下文（analysis/retrieval.py）

- current 候选：active 当前 Revision，实体优先、主题次之；active 数量 ≤ 30 视为全量扫描；
- historical 候选：仅 `change_signal != none` 的 Claim 触发，召回 obsolete 当前 Revision，只用于 updates 解释；
- 上下文状态由确定性代码计算：`sufficient / partial / insufficient` + `reason_codes`（rule_complete、no_active_memory、candidate_truncated、unmatched_claim_without_full_scan、historical_update_signal、retrieval_error）。

### 3.4 Compare 与 Delta（analysis/compare.py）

- LLM 只输出逐 Claim 关系：唯一 `primary_relation` + 多 `matches` 解释证据，无聚合列表；
- 结构校验：Claim ID 集合与输入完全一致；match 必须引用当次候选；`new` 时 matches 为空；contradicts 必须带冲突摘要；
- `derived_summary` 由代码聚合：按角色统计关系数量、known_duplicate（引用 awareness=known 的 current 候选才算"用户已知"）、cognitive_gain（new/extends/complements/contradicts/updates）分层、unused 候选。

### 3.5 Evaluate 接入

- 输入新增 Current User State 快照与 Delta 摘要；无 Delta（Memory 为空、召回失败、Compare 失败或 legacy）时保守降级，不生成占位 Delta；
- Prompt 明确：只有 Delta 证据支撑才可声称"你已经知道"；召回上下文有限时保持保守。

## 4. Worker 流水线

六阶段：`triage → analyze → persist_claims → retrieve_memory → compare → evaluate → completed`

- 首次领取创建 Content Revision 并关联；正文哈希变化时创建新 Revision 并从 triage 重新开始；
- Compare 失败不阻塞分析：CompareRun 保留失败原因，Evaluate 保守完成；
- `POST /analyses/{id}/retry-compare` 单独重试（仅限未完成分析），不重跑 Evaluate、不改写历史 Delta。

## 5. API 变更

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/memory` | 认知记忆列表（当前版本 + 版本数） |
| GET | `/api/v1/memory/{id}` | 版本历史 + 确认记录 |
| POST | `/api/v1/memory` | 手工录入（先 Memory Match） |
| POST | `/api/v1/memory/{id}/revisions` | 追加 Revision（expected 冲突返回 409） |
| GET | `/api/v1/memory/proposals` | 待确认修改建议 |
| POST | `/api/v1/memory/proposals/{id}/decision` | 接受/拒绝（RESOLVE_MATCH 可指定合并目标） |
| GET/PUT | `/api/v1/user-state` | 当前阅读状态 |
| GET | `/api/v1/analyses/{id}/compare` | Compare 完整输入/输出/召回上下文 |
| POST | `/api/v1/analyses/{id}/retry-compare` | 单独重试 Compare |
| POST | `/api/v1/analyses/{id}/claims/{claim_id}/feedback` | Claim 级知晓/立场确认（含根因分流） |
| POST | `/api/v1/analyses/{id}/claims/{claim_id}/correction` | 关系/角色高级纠错 |

已有接口变更：`contents` 详情返回行级 `claims`、`cognitive_delta`（原始关系 + effective 关系 + 纠错记录）、`retrieval_context_status`；列表返回简短 `delta_summary`；队列 `stage` 枚举扩展。

## 6. Web 变更

- **详情页**：新增"与已有认识的差异"区块——已知重复/新增/扩展/补充/冲突/更新分区展示、召回上下文状态提示、逐 Claim 知晓与立场确认按钮（我早已知道/这次新学到/不确定/五个立场）、默认折叠的"为什么这样判断？"高级纠错入口（关系与角色下拉）；
- **认知记忆页**（`/memory`）：手工录入、版本历史、确认记录、待确认 Proposal 接受/拒绝/合并、修改 awareness/stance/lifecycle 追加版本；
- **当前阅读状态页**（`/user-state`）：目标、问题、上下文、时间预算、深度、探索意愿、有效期；
- **Inbox**：卡片显示简短 Delta 摘要（认知增量/已知重复数量）；
- 导航新增"当前状态"与"认知记忆"。

## 7. 测试

新增 5 个后端测试文件（`test_claims`、`test_memory`、`test_compare`、`test_user_state`、`test_feedback`），覆盖：

- Claims：旧格式兼容、ID 幂等分配、section_ref 校验、Revision 幂等；
- Memory：exact_text 等价确认不重复创建、召回后 high 置信才自动合并、无效 Revision 降级、无候选视为不同、uncertain 生成 Proposal、Proposal 接受/拒绝/过期冲突、API 写入全流程；
- Compare：结构校验拒绝违规输出、known_duplicate 与 gain 分层聚合、召回上下文状态规则、Worker 全流程 Delta 持久化、Compare 失败保守降级；
- User State：API 读写、Evaluate 前快照创建与复用、过期回退；
- Feedback：Claim 反馈创建/确认 Memory、根因分流持久化、纠错原始值与 effective 展示、非候选证据拒绝。

## 8. 与方案的可验证差异与简化

如实记录本次实现与 002 方案文档的差异：

1. **`claim` 字段名保留**：方案 5.1 建议输出字段名为 `statement`，实现沿用现有 `ContentClaim.claim` 命名，避免破坏旧数据兼容；语义相同（规范化主张表达）；
2. **Memory Match 的 cognitive_delta 复用分支已实现但未由反馈路径传入**：`run_memory_match(delta_matches=...)` 支持复用 Delta matches，但 `apply_claim_feedback` 当前未传该参数（需要按 Claim 查询最近 Compare Run 的 matches，作为后续接入点）；当前生效路径为文本匹配 → 实体/主题召回 → LLM；
3. **旧分析不回填 Revision 与行级 Claims**：方案 12.4 允许机械回填，实现选择保持 legacy 不伪造（开发库无历史正式数据，回填无收益）；
4. **`claim_feedback_events` 为新增表**：方案 11.2 要求保存用户动作与来源，未指定表名，实现新增独立 append-only 记录表；
5. **retry-compare 仅限未完成分析**：方案 13.2 未限定状态，实现选择对 `completed` 分析返回 409，避免任何改写历史 Delta 的路径；
6. **RESOLVE_MATCH 的"仍然创建新项"仍会再次执行 Memory Match**：方案 6.5 要求接受 Proposal 也遵守 6.4；实现中用户选择创建新项后若再次 uncertain 则标记 stale 并提示重新确认；
7. **无实体/主题的 Claim 召回**：方案 8.1 未规定空实体/主题行为，实现补充"最近候选"回退（`others` 分支），保证仍能执行语义判断而不是直接当新知识；
8. **`derived_summary` 附带 `retrieval_context_status` 一并传给 Evaluate**：方案 10.2 要求 `new` 结合召回上下文状态保持保守，实现直接把状态字段带入 Evaluate 输入；
9. **`analyses.retrieval_context_status` 在 Compare 失败时保持检索得到的值**：失败降级时保留上次计算值用于展示"召回上下文不足"，不伪造 Delta；
10. **旧格式 Claims 的默认角色为 `detail`**：方案未规定，实现选择最保守的边缘细节角色，避免旧分析假装拥有可靠核心判断。

## 9. 未实施（明确不做）

- O0～O2 Prompt 自提升链路（Bundle、Diagnoser、Optimizer、影子验证）；
- Current User State 自动提议；
- 向量召回、知识图谱、全量 Claims 两两比较；
- 反馈差异整理与画像修改建议（沿用现有校准统计）；
- 忽略内容抽检。

## 10. 验证结果

| 门禁 | 结果 |
| --- | --- |
| 后端 `pytest` | 67 passed |
| 后端 `ruff check src tests` | 通过 |
| 前端 `vue-tsc --noEmit` | 通过 |
| 前端 `npm test`（vitest） | 20 passed |
| 前端 `npm run build` | 通过 |
| `git diff --check` | 通过 |
