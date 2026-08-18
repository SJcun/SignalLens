---
title: SignalLens 下一阶段升级方案：Memory V1 主线与 Prompt 自提升副线
version: Draft V0.5.1
status: 未开始
date: 2026-08-18
---

# SignalLens 下一阶段升级方案：Memory V1 主线与 Prompt 自提升副线

## 0. 结论

SignalLens “越来越准确”的核心主线，不是先让 Prompt 自己改写，而是先让系统能够可靠回答：

1. 用户已经明确知道什么；
2. 当前文章提出了哪些可定位的 Claims；
3. 新 Claims 与用户已有认知是重复、扩展、补充、冲突还是更新；
4. 当前阅读目标、时间和探索意图是什么；
5. 基于上述证据，用户应该忽略、读摘要、选择性阅读还是精读。

下一阶段优先建设 Memory V1：

```text
AnalyzeContent
  ↓
持久化 Claims 与来源
  ↓
召回 Cognitive Memory 候选
  ↓
CognitiveCompare
  ↓
CognitiveDelta
  ↓
EvaluateForUser
  + Current User State
  ↓
阅读建议与可解释的新旧认知差异
```

在这条主线稳定后，再建立第二条优化链路：

```text
用户对推荐、Delta 和 Memory 的纠错
  ↓
修正或补充经确认的 Cognitive Memory
  +
诊断 Claim / Compare / Evaluate 的系统性错误
  ↓
已配置 LLM 生成候选 Prompt Bundle
  ↓
门禁、可选回放、后续内容影子验证
  ↓
启用或回滚 Prompt 版本
```

两条链路的关系是：

> **Memory V1 提供准确判断所需的认知事实；反馈与 Prompt 自提升在这些事实之上持续校准系统。**

Prompt 自提升方案保留，但不再是下一阶段的第一优先级，也不能用来掩盖 Memory、召回、Schema 或数据缺失。

本文只设计机制。云服务中的正式文章不作为开发输入，开发者不读取、导出或复制文章；机制部署后在正式环境内原地处理 Claims、Memory、Delta 和用户反馈。

Draft V0.5.1 不改变 V0.5 的总体架构，只补齐四个编码前边界：obsolete 历史召回、CREATE 前 Memory Match 与 Confirmation Event、多 Memory 的主关系选择，以及默认折叠的 Compare / Claim Role 纠错。本文作为 Memory V1 的开发基线；除非实现中发现新的数据语义冲突，否则停止继续扩展方案，按 `M0 → M1 → M2 → M3` 实施，再进入 `O0 → O1 → O2`，本阶段不扩展 Current User State 自动提议能力。

---

## 1. 当前实现与真正缺口

项目当前已经具备：

- `TriageContent → AnalyzeContent → EvaluateForUser` 三阶段分析；
- `AnalyzeContent.claims` 文章级 Claims；
- 摘要、Content Map、观点、限制、不确定性和未验证主张；
- 显式 `UserProfile`；
- `EvaluateForUser` 中的 `knowledge_overlap`、`known_or_redundant` 和 `novel_information`；
- 阅读后反馈、AI 结果快照和基础校准统计；
- Pydantic 结构化输出校验、模型与 Prompt 版本记录；
- SQLite、持久化 Worker 和失败重试。

但目前的“已知 / 新增”仍主要由单次 Evaluate 猜测：

1. Claims 只嵌在 `content_analysis_json` 中，没有稳定行级身份；
2. Claim 缺少可靠的 `section_ref`、文章内部角色、主题、实体和比较所需元数据；
3. 没有长期保存的 Cognitive Memory；
4. 现有 `known_topics` 是主题级弱先验，不能证明用户知道具体 Claim；
5. 没有 Current User State 与每次分析使用的状态快照；
6. 没有候选 Memory 召回；
7. 没有独立 Cognitive Compare 阶段；
8. 没有可持久化、可纠错的 Cognitive Delta；
9. Evaluate 同时承担“猜用户已知”和“给阅读建议”两种职责；
10. 用户反馈不能精确指出是 Memory 错、Compare 错还是 Evaluate 错；
11. Prompt 校准尚不能应用到后续模型调用。

因此，当前优先级不是继续调 `EVALUATE_SYSTEM_PROMPT`，而是把它缺少的认知输入补齐。

---

## 2. 五个核心概念

| 概念 | 回答的问题 | 是否包含用户信息 | 是否决定阅读建议 |
| --- | --- | --- | --- |
| Claims | 文章具体说了什么 | 否 | 否 |
| Cognitive Memory | 用户对具体认知是否知晓、持何立场、当前是否有效 | 是 | 否 |
| Current User State | 用户此刻为什么读、关注什么、能投入多少时间 | 是 | 否 |
| Cognitive Compare | 新 Claims 与候选 Memory 是什么关系 | 是 | 否 |
| Cognitive Delta | 本文相对已记录认知真正增加、重复、冲突或更新了什么 | 是 | 作为 Evaluate 的证据 |

### 2.1 Claims

Claims 是文章本身提出的可独立比较的主张，不等于摘要段落，也不等于用户认知。

Claims 必须：

- 忠于原文；
- 能定位到来源章节；
- 区分事实、解释、观点、预测、建议和定义；
- 区分核心观点、重要支撑和边缘细节；
- 保留原文证据状态；
- 不读取或猜测用户画像；
- 在一次 Analysis 内拥有系统生成的稳定 ID。

### 2.2 Cognitive Memory

Cognitive Memory 是为阅读分诊服务的紧凑认知状态，不是文章收藏库，也不是通用知识库。

它只保存：

- 用户明确录入的知识点；
- 用户对具体 Claim 的直接确认；
- LLM 根据反馈提出且用户接受的 Memory 修改建议；
- 现有认知的冲突、更新和过时状态；
- 每个 Memory 的来源、版本和确认记录。

Memory 必须把三个维度分开保存：

- `awareness_state`：用户是否已经知道；
- `stance`：用户是否认同；
- `lifecycle`：该 Memory 当前是否仍有效。

“知道但反对”是合法且重要的状态，不能因为 `stance = reject` 就把内容当成新知识。

它不保存：

- 全量文章正文；
- 所有历史 Claims 的副本；
- 根据点击、停留或一次阅读自动推断的兴趣；
- 未经确认的 LLM 猜测；
- 面向通用问答的长期知识库。

### 2.3 Current User State

Current User State 表示当前阶段的阅读上下文，与长期画像和长期认知分开：

- 当前目标；
- 当前关注的问题或项目；
- 当前可投入时间；
- 当前希望的阅读深度；
- 当前探索意愿；
- 状态有效期。

时间预算只影响阅读成本和计划，不应把长文章判成低价值。

### 2.4 Cognitive Compare

Cognitive Compare 是独立模型阶段，只负责比较：

```text
Current Claims
vs
Retrieved Cognitive Memories
```

它不生成最终推荐，不修改 Cognitive Memory，也不重新总结全文。

### 2.5 Cognitive Delta

Cognitive Delta 是 Compare 的结构化输出，表示“相对已记录认知的变化”。

每个 Claim 只能拥有一个主要认知关系：

```text
duplicate
extends
complements
contradicts
updates
new
```

其中 `new` 的严格含义是“在本次可用、已确认且成功召回的 Memory Revision 中未找到对应认知”，不是断言用户现实中绝对不知道。

`new` 是关系类型；`cognitive_gain` 是更高层的认知增量概念。`new / extends / complements / contradicts / updates` 都可能形成 cognitive gain，二者不得混用。

---

## 3. 不可破坏的产品原则

### 3.1 主题熟悉不等于知识点已知

`known_topics = [MCP]` 只能作为弱先验，不能作为某个 MCP Claim 已知的证据。

只有具体 Cognitive Memory 或用户对具体 Claim 的确认，才能支持 `duplicate` 或高知识重叠判断。

### 3.2 AnalyzeContent 不读取 Memory

`AnalyzeContent` 继续只分析内容本身，避免用户画像污染摘要和 Claims。

### 3.3 Cognitive Compare 不决定价值

重复度高不一定没有价值，冲突或更新可能非常值得读。Compare 只报告关系，由 Evaluate 结合内容信号、探索价值和 Current User State 做判断。

### 3.4 Evaluate 不得猜测用户已知

Evaluate 声称“你已经知道”时，必须引用 Cognitive Delta 中的 Memory Revision 证据。召回上下文不足时必须明确保持不确定。

### 3.5 Memory 修改必须确认

- 用户对具体 Claim 的“是否知道”与“是否认同”分开确认；
- 从自由文本、阅读行为或 LLM 推断出的修改只能形成 Proposal；
- Proposal 未被接受前不能进入正式 Cognitive Memory；
- 冲突不得静默覆盖旧 Memory。

### 3.6 相关性、知识重叠和阅读价值分开

- `relevance`：与当前目标是否相关；
- `knowledge_overlap`：与已确认认知有多少重复；
- `intrinsic_signal`：内容本身质量；
- `exploration_value`：是否拓展认知边界；
- `recommendation`：最终阅读动作。

低相关或高重复不能单独推出 `ignore`。

### 3.7 正式数据不进入开发环境

- 开发只依赖 Schema、接口和最小工程测试夹具；
- 正式文章、Memory 和反馈不下载到开发机；
- 迁移、召回、Compare 和反馈处理均在正式部署内部运行；
- 工程夹具只验证状态机、约束和迁移，不作为 Prompt 效果测试集。

---

## 4. 目标分析架构

```text
Capture
  ↓
Content Revision
  ↓
TriageContent
  │
  └─ manual 且内容有效 → 必须 continue
  ↓
AnalyzeContent
  ↓
Content Claims 持久化
  ↓
Memory Candidate Retrieval
  │  confirmed memories only
  ↓
CognitiveCompare
  ↓
CognitiveDelta 持久化
  ↓
Current User State Snapshot
  ↓
EvaluateForUser
  ↓
Inbox / Detail / Reading Plan
  ↓
用户反馈
  ├─ Memory correction / proposal
  └─ Prompt improvement evidence
```

阶段职责保持单一：

| 阶段 | 输入 | 输出 | 禁止事项 |
| --- | --- | --- | --- |
| Triage | 内容、简要关注主题 | 是否继续分析 | 不做最终推荐 |
| Analyze | 内容、章节索引 | Claims、摘要、结构 | 不读取用户认知 |
| Retrieve | Claim 元数据、已确认 Memory | 候选 Memory IDs | 不判断语义关系 |
| Compare | Claims、候选 Memory | Cognitive Delta | 不给阅读建议、不写 Memory |
| Evaluate | Analysis、Delta、Current State、简要画像 | 阅读建议 | 不自行发明已知状态 |

---

## 5. Claims V1

### 5.1 结构化输出

`AnalyzeContent.claims` 建议演进为：

```json
{
  "statement": "该主张的规范化自然语言表达",
  "claim_type": "fact | interpretation | opinion | prediction | recommendation | definition",
  "claim_role": "core | supporting | detail",
  "change_signal": "none | temporal | version | replacement | deprecation",
  "section_ref": "sec-003",
  "evidence": [
    "原文中的必要证据或证据摘要"
  ],
  "verification": "supported_in_content | unverified | opinion",
  "topics": ["Agent Memory"],
  "entities": ["MCP"]
}
```

模型不生成数据库 ID。系统在持久化时分配 `claim_id`，并关联：

- `analysis_id`；
- `content_revision_id`；
- `section_ref`；
- 模型和 Prompt 版本；
- 创建时间。

`change_signal` 只描述原文是否明确出现时间变化、版本变化、替代或废弃信号，用于触发历史 Memory 召回；没有原文证据时必须为 `none`。

### 5.2 文章内部角色

`claim_role` 使用三个稳定枚举，不引入 0～100 的主观评分：

```text
core
文章成立所依赖的核心观点、结论或主要方法

supporting
支撑核心观点的重要论据、机制、证据或适用条件

detail
局部信息、例子、边缘事实或实现细节
```

同一 Claim 只有一个角色。Evaluate 必须区分核心认知增量与细节数量，不能用大量 `detail + new` 覆盖“核心 Claims 全部重复”的事实。

### 5.3 来源约束

- `section_ref` 必须来自系统生成的章节清单；
- 没有可靠章节引用时允许为空，但不能伪造；
- 证据必须来自当前 Content Revision；
- 正文变化必须创建新 Revision 和新 Analysis；
- 旧 Claim 不随正文覆盖而改变。

### 5.4 Claim 身份边界

V1 不尝试为全世界相同语义的 Claim 建立全局唯一 ID。

`claim_id` 只标识某次内容分析中的一条主张。跨文章是否相同、扩展或冲突，由 Cognitive Compare 判断，避免提前建设知识图谱或复杂语义归并。

---

## 6. Cognitive Memory V1

### 6.1 Memory 逻辑身份

`cognitive_memories` 只保存逻辑身份和当前版本指针：

```text
id
current_revision_id
created_at
```

Memory 的具体内容和状态不在此表原地覆盖。

### 6.2 Append-only Memory Revision

`cognitive_memory_revisions` 保存不可变版本：

```text
id
cognitive_memory_id
version
statement
awareness_state
stance
lifecycle
confidence
topics_json
entities_json
source_type
created_at
confirmed_at
```

`awareness_state` 回答“用户是否已经知道”：

```text
known
uncertain
```

没有对应 Memory 表示“系统没有已确认记录”，不额外创建 `unknown` Revision。

`stance` 回答“用户对该观点持什么态度”：

```text
accept
reject
mixed
undecided
not_applicable
```

事实、定义等不适合表达立场的认知使用 `not_applicable`。观点类 Memory 可以同时是 `awareness_state = known` 和 `stance = reject`。

`lifecycle` 回答当前版本是否仍有效：

```text
active
obsolete
```

`confidence` 表示系统对“该 Revision 是否准确记录用户认知”的把握，不表示主张在客观世界中必然为真。

```text
low
medium
high
```

`source_type`：

```text
manual
claim_feedback
accepted_proposal
```

现有主题级 `known_topics` 始终留在 User Profile 中作为弱先验，不写入 Cognitive Memory。

### 6.3 Memory Evidence

内容来源必须指向具体 Revision：

```text
cognitive_memory_revision_id
content_claim_id
evidence_role
created_at
```

`evidence_role`：

```text
supports
contradicts
updates
origin
```

手工录入的 Memory Revision 可以暂时没有 Content Claim 来源，但必须保留 `source_type = manual` 和用户确认时间。

每个 Revision 拥有自己的 Evidence 关联。新 Revision 如继续沿用旧证据，也必须显式创建关联，不能在读取时偷偷继承当前版本之外的证据。

同一 `(cognitive_memory_revision_id, content_claim_id, evidence_role)` 只保存一次，避免重复来源行。

### 6.4 CREATE 前 Memory Match 与 Confirmation Event

任何来自“我早已知道 / 这次新学到 / 手工录入 / 接受 Proposal”的 CREATE，在写入前都必须执行 Memory Match，不能直接创建新的逻辑 Memory。

V1 使用现有数据完成轻量匹配：

- 规范化文本完全匹配、候选召回和已有 Delta 引用由确定性代码完成；
- 需要判断语义是否等价时，调用项目已经配置的 LLM，并校验结构化输出；
- 不增加新的模型服务，也不让 LLM 直接写入 Memory。

```text
待写入的 Claim 或 statement
  ↓
规范化文本完全匹配
  ↓ 未命中
复用当前 Cognitive Delta 的 matches
  ↓ 仍未命中
按 entity / topic 召回现有 Memory 当前 Revision
  ↓
结构化判断 equivalent / different / uncertain
```

Memory Match 的结果必须经过应用层 Schema 校验：

```text
decision
matched_memory_id
matched_memory_revision_id
candidate_memory_revision_ids
match_source
reason
confidence
```

字段约束：

- `decision` 只能是 `equivalent / different / uncertain`；
- `match_source` 只能是 `exact_text / cognitive_delta / entity_topic / none`；
- `confidence` 只能是 `high / medium / low`；
- `equivalent` 必须且只能指向一个逻辑 Memory 及其当前 Revision；
- `different` 不得填写 matched ID；
- `uncertain` 保留本次实际检查过的全部候选 Revision；仅当召回或模型失败、尚未得到候选时可以为空，并必须写明原因；
- 所有 Revision ID 都必须来自本次匹配流程实际检查过的集合，LLM 不能自行构造。

只有确定性完全匹配，或通过 Schema 校验且 `confidence = high` 的语义判断，才允许自动采用 `equivalent / different`。模型调用失败、结构无效、置信不足或召回上下文不完整时统一降为 `uncertain`，不得冒险合并，也不得绕过匹配直接新建。

处理结果：

```text
equivalent + awareness/stance/lifecycle 未变化
→ 不创建 Memory，不追加 Revision
→ 只追加 Confirmation Event 和必要 Evidence

equivalent + 状态或 statement 发生变化
→ 为原逻辑 Memory 追加 Revision
→ 原子更新 current_revision_id

different
→ 创建新的逻辑 Memory 与 Version 1 Revision

uncertain
→ 不自动合并或创建
→ 生成 RESOLVE_MATCH Proposal，等待用户选择“重试”“合并到现有项”或“仍然创建新项”
```

`memory_confirmation_events` 是 append-only 的用户确认记录：

```text
id
cognitive_memory_id
observed_revision_id
source_type
content_claim_id
source_feedback_id
source_proposal_id
confirmation_type
created_at
```

`observed_revision_id` 固定指向确认发生时看到的 current Revision；`content_claim_id / source_feedback_id / source_proposal_id` 按来源可空，但 `source_type` 与对应来源必须能够追溯本次确认。

`confirmation_type`：

```text
already_known
learned_now
awareness_confirmed
stance_confirmed
source_confirmed
```

Confirmation Event 记录“用户又确认了一次”或“增加了一个来源”，不代表 Memory 内容变化。只有 statement、awareness、stance 或 lifecycle 改变时才创建新 Revision。

### 6.5 Memory Change Proposal

LLM、间接反馈或 `uncertain` 的 Memory Match 只能生成修改建议：

```text
id
action
target_memory_id
expected_current_revision_id
candidate_memory_revision_ids_json
proposed_statement
proposed_awareness_state
proposed_stance
proposed_lifecycle
evidence_claim_ids_json
reason
status
created_at
decided_at
```

`action`：

```text
CREATE
REVISE
MARK_OBSOLETE
REACTIVATE
RESOLVE_MATCH
```

`status`：

```text
pending
accepted
rejected
stale
```

接受 Proposal 时必须检查 `expected_current_revision_id`。若当前版本已变化，Proposal 标记为 `stale` 并要求重新生成或确认，不能覆盖较新的用户修改。`RESOLVE_MATCH` 使用 `candidate_memory_revision_ids_json` 保存用户决策时看到的候选；用户选择合并时还要再次确认候选仍是该 Memory 的 current Revision。

只有 `accepted` 才能改变正式 Memory 状态，但结果仍须遵守 6.4：可创建 Memory、追加 Revision，或在等价且状态未变时只追加 Confirmation Event。拒绝记录保留，防止系统反复提出同一错误建议。

### 6.6 不可变版本规则

- 禁止通过 `UPDATE cognitive_memory_revisions` 覆盖 statement 或状态；
- 创建、修正、改变态度、标记过时或重新激活都追加新 Revision；
- 新 Revision 写入成功后，原子更新 `cognitive_memories.current_revision_id`；
- Revision 的 `(cognitive_memory_id, version)` 必须唯一；
- `updates` 不能直接删除旧认知；
- `contradicts` 默认保留双方证据，用户立场单独保存在 stance；
- Compare Run 保存实际使用的 Memory Revision ID，不只保存 Memory ID 或版本号；
- 后续 Revision 不能重写历史 Cognitive Delta。

例如 Analysis A 使用 `Memory M1 / Revision R2 / Version 2`，即使当前指针以后变成 R5，历史 Analysis 仍必须读取 R2 的完整 statement、awareness、stance、lifecycle 和来源。

---

## 7. Current User State V1

### 7.1 与 User Profile 的区别

| User Profile | Current User State |
| --- | --- |
| 长期兴趣和阅读偏好 | 当前目标和上下文 |
| 更新频率低 | 可随任务或阶段变化 |
| 主题熟悉度是弱先验 | 描述此刻想解决的问题 |
| 不应保存具体已知 Claim | 不承担长期认知存储 |

### 7.2 建议字段

```json
{
  "active_goals": ["了解 Agent Memory 的可靠性设计"],
  "active_questions": ["怎样避免错误记忆被持续放大"],
  "focus_context": "正在设计 SignalLens Memory V1",
  "available_minutes": 20,
  "preferred_depth": "balanced",
  "exploration_level": "medium",
  "valid_until": null
}
```

### 7.3 快照规则

- Current State 由用户显式编辑；
- 不根据浏览次数自动改变；
- Evaluate 前创建不可变 Snapshot；
- Analysis 保存 `current_user_state_snapshot_id`；
- 状态过期时回退到长期 Profile；
- 状态为空不阻止分析，Evaluate 使用保守默认值。

---

## 8. Memory Candidate Retrieval

### 8.1 V1 简单实现

第一版不引入向量数据库。

候选分为两组：

```text
current_memory_candidates
historical_memory_candidates
```

`current_memory_candidates`：

1. 查询当前指针指向 `lifecycle = active` 的已确认 Memory Revision；
2. 优先匹配 Claim 的规范化实体；
3. 再匹配主题；
4. 再考虑最近使用和 stance，但 stance 不影响 awareness 判断；
5. Memory 数量很小时允许在模型上下文预算内传递全部 current Revision。

`historical_memory_candidates`：

1. 仅当 Claim 的 `change_signal != none` 时触发；
2. 使用同一 entity / topic 规则额外召回当前指针指向 `lifecycle = obsolete` 的 Revision；
3. 只召回每个逻辑 Memory 的当前 obsolete Revision，不把全部旧 Revision 塞入模型；
4. 该候选用于识别 `updates` 和解释历史认知，不参与普通 duplicate 已知聚合。

系统保存两组 Revision ID、候选类型和召回原因。obsolete 不等于永久退出召回，但没有时间、版本、替代或废弃信号时不进入普通候选。

召回只缩小候选范围，不直接决定 `duplicate`、`contradicts` 或 `updates`。

### 8.2 本次召回上下文状态

`retrieval_context_status` 只表示“当前系统按照既定召回规则，为本次 Compare 提供的 Memory 上下文状态”，不表示系统知道用户现实中的全部认知，也不证明候选召回语义上绝对完整。

状态继续使用：

```text
sufficient
partial
insufficient
```

该状态由确定性代码计算，LLM 不能输出或修改。Compare Run 同时保存：

```text
total_active_revision_count
total_obsolete_revision_count
entity_match_count
topic_match_count
candidate_count
current_candidate_count
historical_candidate_count
historical_recall_triggered
all_active_scanned
all_eligible_historical_scanned
truncated
retrieval_error
reason_codes
```

`all_eligible_historical_scanned` 表示符合本次 change signal 与 entity / topic 确定性规则的 obsolete current Revisions 已全部检查，不表示扫描所有历史版本。

`reason_codes` 使用确定性枚举：

```text
rule_complete
no_active_memory
candidate_truncated
unmatched_claim_without_full_scan
historical_update_signal
retrieval_error
```

操作定义：

- `insufficient`：召回发生错误，或当前既没有 active Memory Revision，也没有由 change signal 召回的 historical candidate；
- `partial`：只有 historical candidate、候选因上下文预算被截断、存在 active Memory 但部分 Claim 既未获得规则候选也未完成全量扫描，或 `historical_recall_triggered = true` 但 `all_eligible_historical_scanned = false`；
- `sufficient`：召回无错误、未截断，并且每个 Claim 都获得规则候选或 active Memory 已完成全量扫描；带 change signal 的 Claim 还必须满足 `all_eligible_historical_scanned = true`。

这里的 `sufficient` 仍然只表示“规则按设计完整执行”，不等于真实用户认知覆盖完整。

无论状态如何：

- Compare 可以输出“相对已记录 Memory 未找到对应项”；
- 不能把所有 Claims 都断言成用户绝对未知；
- Evaluate 不得因此夸大新颖性；
- UI 显示“本次召回上下文不足或有限”，而不是“这些内容你都不知道”。

具体降级：

- `retrieval_error` 非空时不调用 Compare、不生成占位 Delta，进入保守 Evaluate 降级；
- 没有 active 或 historical candidate 且召回流程正常时，可以把 Claims 表达为“相对当前空记录为 new”，同时保持 `insufficient`，不得宣称用户现实中未知；
- 候选被截断时允许 Compare，但所有 `new` 都必须结合 `partial` 状态解释。

### 8.3 何时再考虑向量召回

只有出现可观测问题时再评估：

- 已确认 Memory 数量明显增长；
- 主题和实体召回频繁漏掉用户确认的相关项；
- 简单候选集持续超过上下文预算；
- 已有真实反馈能衡量候选召回率。

Embedding 即使引入，也只负责候选召回，不能直接决定认知关系。

---

## 9. Cognitive Compare 与 Cognitive Delta

### 9.1 Compare 输入

```text
Current Content Claims
Candidate Cognitive Memories
Memory Revision Metadata
Code-computed Retrieval Context
```

Compare 不读取完整文章正文，只使用 Claims、必要来源片段和候选 Memory，减少成本和提示注入面。

### 9.2 Delta 结构

LLM 只输出逐 Claim 关系，不生成聚合列表：

```json
{
  "relations": [
    {
      "current_claim_id": "claim-new",
      "primary_relation": "updates",
      "matches": [
        {
          "memory_revision_id": "memory-revision-v2",
          "candidate_kind": "historical",
          "relation": "updates",
          "reason": "新版本明确替代旧版本行为"
        },
        {
          "memory_revision_id": "memory-revision-v3",
          "candidate_kind": "current",
          "relation": "contradicts",
          "reason": "与另一条当前认知结论互斥"
        }
      ],
      "added_information": "记录了新版本行为及替代边界",
      "conflict_summary": "与一条当前认知存在冲突",
      "reason": "存在明确版本替代，因此主关系选择 updates",
      "confidence": "high"
    }
  ]
}
```

每个当前 Claim 必须恰好出现一次，并且只能有一个 `primary_relation`。

结构校验还必须保证：

- `current_claim_id` 集合与 Compare 输入 Claim ID 集合完全相同且无重复；
- 所有 `matches[].memory_revision_id` 都来自本次 current 或 historical 候选集合；
- `matches[].candidate_kind` 必须与候选来源一致；
- `matches[].relation` 只能是 `duplicate / extends / complements / contradicts / updates`，`new` 不能作为 match 关系；
- `primary_relation = new` 时 `matches` 必须为空；
- 其他关系至少包含一个 match，且 `primary_relation` 必须至少与一个 `matches[].relation` 相同；
- `primary_relation = contradicts` 时必须提供 `conflict_summary`。

系统将 LLM 输出与代码生成的召回上下文组合成持久化 Cognitive Delta：

```text
retrieval_context
relations
derived_summary
```

`derived_summary` 由确定性代码根据 `primary_relation + claim_role` 计算，例如：

```text
relation_counts_by_role
duplicate_claim_ids
known_duplicate_claim_ids
uncertain_overlap_claim_ids
cognitive_gain_claim_ids
core_gain_claim_ids
supporting_gain_claim_ids
detail_gain_claim_ids
unused_candidate_memory_revision_ids
```

禁止让 LLM 同时维护 `known_items / new_items / extensions / conflicts / updates` 等重复聚合字段，避免一个 Claim 被重复计数或 Schema 自相矛盾。

`matches` 只保存多 Memory 的解释证据，不参与数量累计；只有 `primary_relation` 进入统计和 cognitive gain。

`known_duplicate_claim_ids` 还必须满足：至少一个 `duplicate` match 来自 current candidate，且对应 Revision 的 `awareness_state = known`。historical candidate 即使语义重复，也只能用于历史解释，不能证明用户当前仍然知道。

`cognitive_gain` 的确定性定义是：`primary_relation` 属于 `new / extends / complements / contradicts / updates`。是否值得投入注意力仍由 Evaluate 结合 `claim_role`、内容信号和 Current User State 判断。

### 9.3 关系判定约束

- `duplicate`：当前 Claim 与已确认 Memory Revision 表达同一核心信息；只有所引用 Revision 的 `awareness_state = known` 才能进入“用户已知”聚合，`uncertain` 只能表示语义重合但知晓状态未确认；用户 stance 即使为 reject，也不改变关系；
- `extends`：保留原认知并增加重要细节、条件或证据；
- `complements`：相关但从不同角度补充；
- `contradicts`：两者在相同时间与适用范围内不能同时成立，或命题方向直接冲突；用户 stance 不参与该关系判定；
- `updates`：当前 Claim 提供更新版本、时间状态或替代结论；
- `new`：本次可用、已确认并成功召回的 Memory Revision 中没有对应项。

高语义相似不能覆盖方向相反的结论；有时间变化时不能简单判成重复。

### 9.4 多 Memory 匹配时的主关系选择

一个 Claim 可以匹配多个 Memory Revision，并在 `matches` 中保留不同关系，但主关系仍然只有一个。选择顺序：

1. 存在明确时间、版本、替代或废弃关系时，`updates` 优先于字面冲突；
2. 保留旧结论并增加重要条件、边界或证据时选择 `extends`；
3. 结论可同时成立、但提供不同侧面时选择 `complements`；
4. 在相同时间和适用范围内结论互斥，且不存在明确前后替代时选择 `contradicts`；
5. 核心语义相同且没有重要新增时选择 `duplicate`；
6. 没有可引用匹配时选择 `new`。

例如“2025 年 API 使用 X”与“2026 年 API 已改为 Y”在字面上冲突，但存在明确时间继承，应以 `updates` 为主关系；`contradicts` 可以保留在其他 match 中用于解释。

### 9.5 Compare 的硬边界

- 不修改 Memory；
- 不生成推荐；
- 不把主题相同直接判成重复；
- 不把召回失败当成用户无知；
- 不根据 stance 推断 awareness；
- 每个 Claim 恰好输出一个 `primary_relation`；
- 每个非 `new` 关系必须引用 Memory Revision ID；
- `new` 的 `matches` 必须为空；
- 多个 match 不得产生多个统计关系；
- historical candidate 不参与普通 duplicate 已知聚合；
- 每个关系必须引用当前 Claim ID；
- 不确定时降低 confidence，不伪造对应关系。

---

## 10. EvaluateForUser 的新职责

### 10.1 输入

```text
AnalyzeContent
CognitiveDelta
Current User State Snapshot
Compact User Profile
```

Evaluate 不再接收完整 Cognitive Memory，也不再自行做跨历史比较。

### 10.2 判断逻辑

- 引用 `awareness_state = known` Revision 的 `core + duplicate`，对知识重叠的影响高于 `detail + duplicate`；
- 引用 `awareness_state = uncertain` Revision 的 duplicate 不能被展示成“你已经知道”；
- `core / supporting` 的 `new / extends / complements / contradicts / updates` 优先构成重要认知增量；
- 大量 `detail + new` 不能自动推出高认知增量或全文精读；
- `new` 需要结合代码计算的召回上下文状态，状态有限时保持保守；
- Current State 决定当下相关性和阅读安排；
- 内容信号与探索价值继续独立；
- 长度和可用时间只影响 Reading Plan，不降低文章价值；
- 高探索价值内容不能建议 `ignore`；
- 手动提交的有效内容不能被静默过滤。

### 10.3 输出可解释性

`recommendation_reason` 使用代码聚合后的 Delta 摘要，例如：

```text
核心 Claims：2 项重复，0 项产生认知增量
重要支撑：1 项扩展，1 项冲突
边缘细节：3 项 new
本次召回上下文：partial
```

Reading Plan 应优先定位承载 `core / supporting` 认知增量的章节，不能仅按新细节数量安排精读。

### 10.4 降级策略

Memory 为空、召回失败或 Compare 失败时：

- 分析结果仍可展示；
- 明确标记 `retrieval_context_status`；
- Evaluate 回退到当前保守逻辑；
- 不得声称具体内容已知；
- 不生成占位 Delta；
- Worker 保留失败原因，允许单独重试 Compare。

---

## 11. 用户反馈与 Memory 更新

### 11.1 低成本反馈

保留现有文章级反馈，并增加对高影响 Delta 的轻量纠错：

```text
这个知识点：

知晓状态：
[我早已知道] [这次新学到] [我还不确定是否理解]

观点立场：
[我认同] [我不认同] [部分认同] [尚未决定] [不适用]
```

两个维度独立展示、允许组合；事实和定义默认使用 `stance = not_applicable`。不要求用户逐条审核所有 Claims，只展示影响推荐的少量项目。

### 11.2 直接确认

用户对具体 Claim 的明确操作先形成目标状态，再进入 6.4 的 Memory Match：

- `我早已知道` → `awareness_state = known`；
- `这次新学到` → `awareness_state = known`，并关联当前 Claim 与确认时间；
- `我还不确定是否理解` → `awareness_state = uncertain`；
- `我认同 / 我不认同 / 部分认同` → `stance = accept / reject / mixed`；
- `尚未决定 / 不适用` → `stance = undecided / not_applicable`。

用户明确选择观点立场，说明已经接触并理解到足以表态；若当前没有对应 Memory，可同时记录 `awareness_state = known`。但系统不能从文章作者立场、点击或 LLM 推断用户 stance。

Memory Match 找到等价项且目标状态未变化时，只追加 Confirmation Event 和必要 Evidence；只有目标状态变化时才携带 `expected_current_revision_id` 追加 Revision。若当前指针已变化，返回冲突并要求用户基于新版本重新确认。

系统必须保存用户动作、Claim 来源和时间。

### 11.3 间接信号

下列信号不能直接写 Memory：

- 点击或停留；
- 阅读完成；
- `new_knowledge = yes` 但没有具体 Claim；
- 自由文本中的模糊表达；
- LLM 从摘要或 Key Takeaway 推断出的知识变化。

这些信号只能生成 Memory Change Proposal，等待用户确认。

### 11.4 高级关系与 Claim 角色纠错

默认反馈仍保持轻量。内容详情在“为什么系统这样判断？”中提供折叠的高级纠错入口：

```text
实际关系：
[重复] [扩展] [补充] [冲突] [更新] [全新]

该 Claim 在文章中的角色：
[核心] [重要支撑] [边缘细节]
```

高级纠错写入 append-only `claim_corrections`：

```text
id
analysis_id
content_claim_id
cognitive_compare_run_id
correction_type
original_value
corrected_value
matched_memory_revision_ids_json
evidence_status
reason
created_at
```

`correction_type`：

```text
primary_relation
claim_role
```

`evidence_status` 使用 `complete / incomplete / not_applicable`；claim_role 纠错使用 `not_applicable`。

primary_relation 纠正为 `new` 时使用 `not_applicable`；纠正为非 `new` 且引用有效 Memory Revision 时使用 `complete`，暂时没有可引用证据时使用 `incomplete`。

规则：

- 原始 Claim、Compare 输出和 Cognitive Delta 保持不变；
- API 和 Web 同时展示原始值与最新用户纠正后的 effective value；
- relation 从 `new` 改为其他值时，可从当次候选中选择证据 Revision；没有证据时仍可保存关系标签，但将 `evidence_status` 标记为 `incomplete`；
- correction 只作为用户 Ground Truth、统计和未来 Prompt Diagnoser 输入，不自动重跑历史推荐；
- claim_role 纠错率和 Compare 关系准确率只使用这些显式 correction 计算，不能从点击或停留推断。

### 11.5 反馈分流

一次反馈可能指出不同根因：

```text
memory_awareness_change
memory_stance_change
memory_lifecycle_change
state_error
retrieval_error
claim_extraction_error
claim_role_change
compare_error
compare_relation_change
evaluation_error
summary_error
insufficient_evidence
```

只有先分清根因，后续 Prompt 自提升才不会用 Prompt 修改掩盖 Memory 或数据问题。

---

## 12. 持久化与历史可复现

### 12.1 新增实体

建议增加：

```text
content_revisions
content_claims
cognitive_memories
cognitive_memory_revisions
cognitive_memory_evidence
memory_confirmation_events
memory_change_proposals
claim_corrections
current_user_state
current_user_state_snapshots
cognitive_compare_runs
```

### 12.2 Analysis 关联

`analyses` 建议增加：

```text
content_revision_id
current_user_state_snapshot_id
cognitive_compare_run_id
retrieval_context_status
```

`cognitive_compare_runs` 保存：

```text
analysis_id
current_claim_ids_json
current_memory_candidate_revision_ids_json
historical_memory_candidate_revision_ids_json
retrieval_context_json
compare_output_json
derived_summary_json
model
prompt_version
status
last_error
created_at
completed_at
```

### 12.3 历史规则

- Analysis 使用的 Claim、Memory Revision 和 Current State 必须可还原；
- Compare Run 必须直接保存 Revision ID，不能只保存逻辑 Memory ID 或版本数字；
- Compare Run 必须保留 current 与 historical 两组候选，不能只保存最终被引用的 matches；
- Memory 后续变化不能改写旧 Delta；
- Confirmation Event 和 Claim Correction 只追加，不覆盖用户历史动作；
- 同一 URL 正文变化创建新 Content Revision；
- 旧 Analysis 继续展示原结果；
- 缺少完整上下文的旧记录标记 `legacy`，不伪造 Delta。

### 12.4 正式环境迁移

迁移前创建可恢复 SQLite 备份，并用临时数据库验证。

推荐顺序：

1. 创建 Content Revision 和 Claims 表；
2. 在正式数据库内机械回填可确认的现有正文版本与 Claims；
3. 回填不调用 LLM、不导出正文；
4. 缺少新字段或可靠来源的旧 Claims 标记为 legacy，不直接进入正式 Compare；
5. 创建 Memory、Memory Revision、Evidence、Confirmation Event、Proposal、Claim Correction 和 Current State 表；
6. 现有 `known_topics` 保留为弱先验，不自动转换成 confirmed Memory；
7. 创建 Compare Run 并为 Analysis 增加可空关联；所有新 Compare 只引用 Revision ID；
8. 新 Analysis 使用完整新链路；
9. 旧 Analysis 无法精确还原时保持 legacy；
10. 不删除现有 Content、Analysis、Feedback 或校准决定；
11. Windows 测试显式释放 SQLite 文件句柄。

---

## 13. Worker、API 与 Web

### 13.1 Worker

目标阶段：

```text
triage
analyze
persist_claims
retrieve_memory
compare
evaluate
completed
```

要求：

- 继续复用现有 OpenAI-compatible Provider；
- 每个模型阶段前检查分析时段；
- 每阶段结果独立持久化；
- Compare 失败可单独重试；
- change signal 触发时额外召回 obsolete current Revision；
- 正文哈希变化时从 Analyze 重新开始；
- Current State 与 Memory current Revision 变化不自动重写已完成历史；
- Memory 修改通过追加 Revision 完成，Worker 不覆盖旧 Revision；
- Memory CREATE 服务先执行 Match；状态未变时只写 Confirmation Event；
- 不引入 Redis、Celery、Kafka 或新微服务。

### 13.2 API

建议能力，最终路径在实施时按现有 `/api/v1` 风格确定：

- 查看和修改 Current User State；
- 查询 Cognitive Memory 当前 Revision 与完整历史；
- 查询 Memory 的 Confirmation Events 和来源；
- 手工创建或追加 Memory Revision，分别修改 awareness、stance 和 lifecycle；
- CREATE 前预览 Memory Match，并处理 uncertain 的合并 / 新建选择；
- 所有追加 Revision 的请求携带 expected current revision，冲突时返回明确错误；
- 查询待确认 Memory Change Proposal；
- 接受或拒绝 Proposal；
- 查看某次 Analysis 的 Claims；
- 查看 Cognitive Delta 及引用证据；
- 对高影响 Delta 分别提交知晓状态和观点立场纠错；
- 提交或查询 primary_relation / claim_role 高级纠错；
- 重试 Compare。

所有修改操作只允许 admin Web 会话。插件 Key 仍只能 Capture。

### 13.3 Web

内容详情新增：

```text
你已经知道
本文真正新增
对已有认识的扩展
与已有认识的冲突
旧信息更新
本次召回上下文状态
```

Memory 页面提供：

- 已确认 Memory 的 awareness、stance 和 lifecycle；
- 来源 Claim；
- 不可变 Revision 历史；
- Confirmation Event 历史；
- 待确认修改建议；
- 接受、拒绝、手工修正；
- 当前阅读状态。

内容详情的高级纠错默认折叠，只在用户展开解释时显示；普通阅读反馈不增加额外必填项。

Inbox 只显示简短的 Delta 摘要，不堆叠复杂关系图。

---

## 14. Memory 主线实施阶段

### M0：Claims 与证据基础

#### 范围

1. 增加 Content Revision；
2. 扩展 Claim Schema；
3. Claim 增加可靠 `section_ref`、`claim_role`、`change_signal`、类型、主题和实体；
4. 将 Claims 持久化为行级记录；
5. Analysis 关联 Content Revision；
6. 兼容读取旧 `content_analysis_json`。

#### 验收

- Analyze 不读取用户数据；
- 每条新 Claim 有稳定 ID；
- 每条 Claim 的 `claim_role` 只能是 core / supporting / detail；
- `change_signal` 没有原文证据时必须为 none；
- 可引用的 Claim 都能定位当前正文；
- 正文变化不会覆盖旧 Claim 证据；
- 旧分析不丢失；
- 无需访问云端文章即可完成开发验证。

### M1：Cognitive Memory 与 Current User State

#### 范围

1. 增加 Memory 逻辑身份、append-only Revision、Evidence、Confirmation Event 和 Proposal；
2. 增加 Current User State 与 Snapshot；
3. 提供 CREATE 前 Memory Match 和手工 Memory 管理；
4. 提供 Proposal 接受 / 拒绝；
5. 通过 current revision 指针和 Revision ID 保留完整历史与来源；
6. 将现有 known topics 保持为弱先验。

#### 验收

- 未确认 Proposal 不参与正式分析；
- 等价 Memory 且状态未变化时不创建新 Memory 或 Revision；
- 重复确认通过 Confirmation Event 保存；
- Memory Match 调用失败、输出无效或置信不足时转为待确认 Proposal，不自动合并或创建；
- Memory 修改只追加 Revision，不覆盖旧内容；
- awareness、stance 和 lifecycle 可以独立表达；
- 冲突不会覆盖旧 Memory；
- 每个内容来源 Memory 可追溯到 Claim；
- Current State 与长期 Profile 分离；
- Current State 空时安全回退；
- 不通过行为自动强化兴趣或认知。

### M2：Cognitive Compare 与 Delta

#### 范围

1. 实现 current / historical 双候选召回和代码计算的 retrieval context；
2. 定义“每个 Claim 唯一 primary_relation + 多 matches”的 Cognitive Delta Schema；
3. 增加 Compare Prompt 和 Pipeline 阶段；
4. 分组持久化 current / historical 候选 Revision IDs、召回上下文、Delta、模型和 Prompt；
5. 支持 Compare 单独重试；
6. Web 展示 Delta 与证据。

#### 验收

- duplicate / extends / complements / contradicts / updates / new 可区分；
- 每个 Claim 恰好一个 primary_relation；
- 每个非 new 关系引用 Memory Revision；
- 多 Memory 关系只进入 matches，只有 primary_relation 参与统计；
- 存在明确时间或版本替代时 updates 优先于 contradicts；
- 带 change signal 的 Claim 能额外召回相关 obsolete Revision；
- 聚合统计和 cognitive gain 由代码生成，不由 LLM 重复填写；
- retrieval context 状态由代码生成，不由 LLM 判断；
- 每个关系引用当前 Claim；
- 同主题但不同结论不会直接判重复；
- 召回不足时明确标记覆盖度；
- Compare 不写 Memory、不生成推荐。

### M3：Evaluate 接入与反馈闭环

#### 范围

1. Evaluate 输入 Cognitive Delta 和 Current State；
2. 从 Evaluate 移除无证据的已知推断；
3. Reading Plan 按 claim_role 关联高价值 Delta Claims；
4. 增加 awareness 与 stance 分离的 Claim 级轻量反馈；
5. 增加默认折叠的 primary_relation / claim_role 高级纠错；
6. 直接确认经过 Memory Match，间接信号生成 Proposal；
7. 增加根因分流。

#### 验收

- “你已经知道”有 Memory 证据；
- “你已经知道”不受 reject stance 干扰；
- 每项 cognitive gain 引用 Claim，且不与 primary_relation 重复计数；
- 核心 Claims 全部重复时，不因大量新细节自动建议精读；
- 冲突和更新不会被摘要丢失；
- 用户可以纠正错误关系；
- 用户可以纠正 claim_role，所有纠错保留原始值并形成 Ground Truth；
- 未消费文章保持未知；
- Memory 变更不改写历史 Delta；
- 推荐仍保护手动提交和高探索价值内容。

只有 M0～M3 稳定后，Prompt 自提升才进入实施主序列。

---

## 15. 第二优化链路：反馈与 Prompt 自提升

### 15.1 为什么必须建立在 Memory 之上

没有 Memory 和 Delta 时，“推荐偏低”可能来自：

- 用户其实已经知道，但系统不知道；
- 用户并不知道，但 Evaluate 错估；
- Claim 抽取漏掉新增信息；
- Memory 候选召回失败；
- Compare 把扩展错判为重复；
- Current State 过期；
- Evaluate Prompt 的价值权重错误。

如果直接改 Prompt，这些根因会混在一起。Memory 主线完成后，反馈才能精确指向具体阶段。

### 15.2 组件保留

Prompt 自提升继续包含：

- Prompt Bundle；
- Improvement Run；
- Feedback Diagnoser；
- Prompt Optimizer；
- 静态门禁；
- 可选历史回放；
- 后续内容影子验证；
- 原子启用；
- 监控与回滚。

同一个项目已配置 LLM 可以承担 Diagnoser 和 Optimizer，但使用不同 System Prompt 与结构化 Schema。

### 15.3 Prompt Bundle

Bundle 包含：

```text
triage_system_prompt
analyze_system_prompt
compare_system_prompt
evaluate_system_prompt
```

每个 Bundle 保存：

```text
id
parent_bundle_id
version
status
generation_model
generation_reason
created_at
activated_at
```

状态：

```text
bootstrap
candidate
active
rejected
rolled_back
```

当前代码中的 Prompt 作为 bootstrap；Memory 主线新增 Compare 后，再形成完整四阶段 Bundle。

### 15.4 根因诊断

Feedback Diagnoser 输入：

- 当时使用的 Claim、Memory Revision IDs 和 Current State；
- Cognitive Delta；
- Evaluate 结果；
- 用户对推荐、Delta 和 Memory 的纠错；
- append-only Claim Corrections 与其证据状态；
- 模型与 Prompt Bundle；
- 产品硬约束。

建议分类：

```text
memory_awareness_change
memory_stance_change
memory_lifecycle_change
state_change
retrieval_change
claim_prompt_change
claim_role_change
compare_prompt_change
compare_relation_change
evaluate_prompt_change
schema_change_request
code_change_request
ui_change
insufficient_evidence
no_change
```

只有 `*_prompt_change` 进入 Prompt Optimizer。其他类型必须进入对应产品流程，不能强制生成新 Prompt。

### 15.5 LLM 生成候选 Prompt

Prompt Optimizer：

- 从当前 Active Bundle 做最小修改；
- 每项变更引用真实反馈和错误簇；
- 只修改被诊断为 Prompt 问题的阶段；
- 未修改阶段与父版本逐字一致；
- 输出完整 Candidate Bundle、理由和风险；
- 不根据单篇文章写标题、URL、领域特例；
- 不修改代码、Schema、Memory 或 Current State。

开发者和用户都不需要手工撰写候选 Prompt。

### 15.6 固定门禁

候选必须保留：

- 低相关不等于低价值；
- 手动提交不静默过滤；
- 不确定时 `continue`；
- 高探索价值不能 `ignore`；
- Analyze 不读取完整用户认知；
- Compare 不写 Memory；
- Compare 不得用 stance 代替 awareness；
- 每个 Claim 只能输出一个 primary_relation；
- 多 Memory 匹配只能进入 matches，统计只使用 primary_relation；
- 明确时间或版本替代必须优先考虑 updates；
- obsolete Revision 只能通过历史候选规则进入 Compare；
- Delta 聚合与召回上下文状态由代码生成；
- Evaluate 的已知判断必须有 Delta 证据；
- Evaluate 必须区分 core / supporting / detail；
- 主题熟悉不等于 Claim 已知；
- 长度不降低价值等级；
- 不制造原文没有的事实、观点或冲突；
- 所有输出继续经过 Pydantic 校验。

候选删除、削弱或绕过这些规则时直接拒绝。

### 15.7 验证与启用

```text
Candidate
  ↓
静态门禁
  ↓
有完整历史快照 → 可选同输入回放
无完整快照 → skipped_no_evidence
  ↓
后续正式内容影子运行
  ↓
用户真实反馈比较
  ↓
确认启用或拒绝
  ↓
在线监控与回滚
```

历史回放不是独立效果测试集，也不是启动条件。正式环境中有可复现记录时自动使用，没有则跳过。

V1 使用受控启用，不直接开放完全自动启用。Prompt 胜负依据是用户反馈、确定性指标、结构化失败率和成本，不是 LLM 自评。

### 15.8 Prompt 自提升实施阶段

#### O0：版本与快照

- 完整四阶段 Prompt Bundle；
- Analysis 记录 Bundle；
- 冻结 current / historical Memory Revision IDs、State、Claim、召回上下文和 Delta 输入；
- Active 指针与回滚。

#### O1：诊断与候选生成

- Diagnoser Schema；
- 根因分流；
- 使用显式 Claim Corrections 作为关系与角色 Ground Truth；
- LLM Candidate；
- 静态门禁；
- Web 只读 diff。

#### O2：影子验证与受控启用

- 可选历史回放；
- 后续内容影子运行；
- 指标比较；
- 用户确认启用；
- 监控与原子回滚。

O0～O2 不阻塞 M0～M3 的 Memory 主线交付。

---

## 16. 效果指标

### 16.1 Memory 主线首要指标

- awareness 误判率：系统声称 known 但用户确认 uncertain，或反之；
- stance 误记率：系统保存的 accept / reject / mixed / undecided 与用户确认不一致；
- lifecycle 误记率：active / obsolete 与用户确认不一致；
- core / supporting 认知增量漏判率；
- duplicate / extends / contradicts / updates 纠错率；
- Delta 关系证据完整率；
- 单个 Claim 出现多个 primary_relation 的次数，目标为 0；
- Memory 候选召回纠错率；
- 带 change signal 的 Claim 召回相关 obsolete Revision 的成功率；
- 等价 Memory 被错误创建为新逻辑 Memory 的次数；
- 状态未变化的重复确认误建新 Revision 的次数；
- Memory Proposal 接受率与拒绝率；
- 无来源或未确认 Memory 进入正式判断的次数，目标为 0；
- 高价值漏判；
- 严重推荐低估。

### 16.2 辅助指标

- Claim `section_ref` 完整率；
- Claim `claim_role` 纠错率；
- primary_relation 显式纠错率；
- Confirmation Event 数量与实际 Revision 变更数量；
- Compare 结构化输出失败率；
- retrieval context 状态及 reason_codes 分布；
- 每篇传入 Compare 的候选数量；
- 历史 Analysis 精确恢复原 Memory Revision 的成功率；
- Analyze、Compare、Evaluate 分阶段成本；
- 用户完成 Claim 级反馈的负担。

### 16.3 Prompt 自提升指标

- Candidate 修复的目标错误簇；
- 高价值漏判是否恶化；
- 已知误判是否恶化；
- Delta 关系纠错率是否改善；
- 结构化输出失败率；
- Candidate 接受、拒绝和回滚次数；
- Active 与 Candidate 成本差异。

点击率、停留时间和阅读完成率只能辅助诊断交互，不能直接决定 Memory、认知关系或 Prompt 胜负。

---

## 17. 风险与控制

| 风险 | 控制方式 |
| --- | --- |
| LLM 把推测写成用户认知 | 未确认内容只能进入 Proposal |
| 用户反对的熟悉观点被当成新知识 | awareness 与 stance 分列，Compare 主要依据 awareness |
| 主题标签造成同主题误杀 | topic 只做弱先验和候选召回 |
| Memory 更新覆盖历史 | Revision append-only，Compare 保存 Revision ID |
| obsolete Memory 永久退出导致 updates 漏判 | change signal 触发 historical candidate recall |
| 重复确认导致 Memory 和 Revision 膨胀 | CREATE 前 Memory Match；状态未变只写 Confirmation Event |
| 错误 Memory 持续放大 | 来源、Revision、用户纠错、冲突并存 |
| Memory 变成通用知识库 | 只保存分诊需要的紧凑认知状态 |
| 大量新细节掩盖核心重复 | claim_role 分层，Evaluate 提高 core / supporting 权重 |
| Delta 关系重复计数 | 每 Claim 唯一 primary_relation，聚合由代码生成 |
| 多 Memory 匹配造成主关系不确定 | matches 保留解释关系，显式优先规则选唯一 primary_relation |
| Compare 缺少真实标签 | 默认折叠的 relation / claim_role 高级纠错 |
| 召回失败被解释成“全新” | 代码计算 retrieval_context_status，并保持 new 的相对语义 |
| Compare 同时承担推荐 | 独立 Schema，禁止输出 recommendation |
| Current State 影响长期兴趣 | 状态有有效期且不回写 Profile |
| 同一 LLM 自我证明 | Prompt 胜负只看用户反馈与确定性指标 |
| 正式文章泄露到开发环境 | 所有数据处理在部署实例内完成 |
| 用户反馈负担过高 | 只展示影响推荐的少量 Claim |

---

## 18. 明确不做

本轮不包括：

- 自动把阅读行为写入 Cognitive Memory；
- 根据近期行为自动提出 Current User State Proposal；
- 未经用户确认自动接受 Memory Proposal；
- 用 known topics 直接生成具体 Memory；
- 通用知识库、知识图谱或全量文章关系图；
- 全量 Claims 两两比较；
- 第一版引入向量数据库；
- 模型 Fine-tuning；
- LLM 修改源代码或 Pydantic Schema；
- 第一版完全自动启用 Prompt；
- 为 Prompt 效果另建脱离正式使用的文章测试集；
- Redis、Celery、Kafka、LangChain 或复杂 Agent Framework；
- PDF、音视频和 RSS Adapter；
- 多用户；
- 自动推送和推荐 Feed。

---

## 19. 推荐的第一批实施任务

下一次进入代码实施时，第一批只做 Memory 主线，不实现 Prompt 自提升。

### 任务 1：Claims 与来源基础

```text
Content Revision
+
Claim Schema 扩展
+
claim_role
+
Claim 行级持久化
+
section_ref 校验
+
旧 Analysis 兼容
```

### 任务 2：Cognitive Memory 与确认机制

```text
Memory 逻辑身份
+
Append-only Revision
+
Evidence
+
Memory Match
+
Confirmation Event
+
awareness / stance / lifecycle
+
Change Proposal
+
接受 / 拒绝
+
版本历史
```

### 任务 3：Current User State

```text
State API
+
State Web
+
Snapshot
+
Analysis 关联
```

### 任务 4：Cognitive Compare 与 Delta

```text
简单候选召回
+
obsolete 历史候选召回
+
代码计算 Retrieval Context
+
Compare Schema / Prompt
+
唯一 primary_relation
+
多 Memory matches 与主关系优先级
+
确定性 Delta 聚合
+
Worker compare 阶段
+
Delta 持久化
+
证据展示
```

### 任务 5：Evaluate 接入与反馈

```text
Evaluate 消费 Delta / State
+
保守降级
+
Claim 级纠错
+
awareness / stance 分离反馈
+
primary_relation / claim_role 高级纠错
+
Memory Proposal
+
根因分流
```

任务 1～5 完成并在正式使用中稳定后，再进入 O0～O2 Prompt 自提升链路。

---

## 20. 总体验收条件

### 20.1 Memory V1 结构验收

1. 新 Analysis 的主要 Claims 有稳定 ID、来源、`claim_role` 和有证据约束的 `change_signal`；
2. AnalyzeContent 不读取用户 Memory；
3. Cognitive Memory 只包含用户明确确认的认知；
4. awareness、stance 和 lifecycle 分列保存，互不替代；
5. Memory 具体内容只存在于 append-only Revision 中；
6. 任意内容或状态修改都追加 Revision，不覆盖旧 Revision；
7. CREATE 前必须执行 Memory Match；
8. 等价 Memory 状态未变化时只写 Confirmation Event 和 Evidence；
9. known topics 不会被当作具体知识点证据；
10. Current User State 与长期 Profile、Cognitive Memory 分离；
11. active current candidates 与 update-triggered historical candidates 分组保存；
12. obsolete Memory 能在 change signal 触发时参与 updates 判断；
13. Compare 能区分 duplicate、extends、complements、contradicts、updates 和 new；
14. 每个 Claim 恰好拥有一个 primary_relation，并可保存多个解释 matches；
15. 非 new 关系能够追溯到 Claim 和 Memory Revision；
16. 只有 primary_relation 参与 cognitive gain 与聚合；
17. retrieval context 状态由代码计算，LLM 不能填写；
18. 召回不足时不会断言用户绝对不知道；
19. Evaluate 的“已知 / 增量 / 冲突 / 更新”来自 Cognitive Delta；
20. Evaluate 能区分核心增量与边缘新细节；
21. Reading Plan 能定位承载重要 Delta 的 core / supporting Claims；
22. 用户可以分别纠正 awareness 和 stance；
23. 用户可以通过折叠入口纠正 primary_relation 和 claim_role；
24. Claim Correction 保留原始值并形成 append-only Ground Truth；
25. 未确认 Proposal 不影响后续正式判断；
26. 历史 Analysis 能精确读取当时使用的 Memory Revision；
27. 正式数据始终留在正式部署环境；
28. 系统仍保护手动提交、探索价值和高价值内容。

### 20.2 必测语义场景

#### Case 1：知道但反对

```text
Memory Revision:
awareness_state = known
stance = reject

新文章再次提出同一观点
```

预期：`primary_relation = duplicate`。不能因为用户反对就判断为新知识。

#### Case 2：扩展不是 new + extends

```text
旧 Memory：方法 X 在条件 A 下有效
新 Claim：方法 X 在条件 A 下有效，并增加失败条件 B
```

预期：只输出 `primary_relation = extends`，并由代码将该 Claim 纳入 cognitive gain；不能同时输出 new。

#### Case 3：核心重复、细节新增

```text
core Claims 全部 duplicate
detail Claims 存在多个 new
```

预期：展示“存在新细节但核心认知增量低”，不能仅按 new 数量自动建议 deep_read。

#### Case 4：没有召回到相关 Memory

预期：只表达“在本次可用、已确认且成功召回的 Memory Revision 中未发现对应认知”，并展示代码计算的 retrieval context 状态；不能表达“用户不知道”。

#### Case 5：历史 Revision 恢复

```text
一个月前 Analysis A 使用 Memory M1 / Revision R2
今天 M1 的 current_revision_id 更新为 R3
```

预期：查看 Analysis A 时仍完整读取 R2 的 statement、awareness、stance、lifecycle、confidence 和来源，不能用 R3 替代。

#### Case 6：obsolete 历史认知被新版本更新

```text
当前 Memory M1 / Revision R3:
statement = 旧版本使用 X
lifecycle = obsolete

新 Claim:
change_signal = version
新版本已改为 Y
```

预期：R3 进入 historical candidates，主关系为 `updates`，不能因为 obsolete 未进入普通候选而退化成 `new`。

#### Case 7：重复确认不制造新 Memory

```text
现有 Memory M1 / Revision R2 已表达 Claim C
用户再次点击“我早已知道”
awareness / stance / lifecycle 均未变化
```

预期：Memory Match 命中 M1，只追加 Confirmation Event 和必要 Evidence；不创建 M2，也不创建 R3。

#### Case 8：一个 Claim 匹配多个 Memory

```text
Claim C 对 R1 = updates
Claim C 对 R2 = contradicts
```

预期：`matches` 同时保留两条解释关系；存在明确版本替代时 `primary_relation = updates`，统计只计一次 updates。

#### Case 9：高级纠错形成 Ground Truth

```text
原始 primary_relation = new
用户在高级入口纠正为 extends
```

预期：原始 Compare 输出保持不变；新增 append-only Claim Correction，API 展示 original 与 effective value，未来 Prompt 评测使用 corrected value。

### 20.3 第二优化链路验收

29. 反馈能够区分 awareness、stance、lifecycle、Memory Match、召回、Claim Role、Compare、Evaluate 和 Prompt 问题；
30. 已配置 LLM 能生成受约束的 Candidate Prompt Bundle；
31. Candidate 不能修改代码、Schema、Memory Revision 和硬产品原则；
32. Candidate 不能重新混合 awareness 与 stance，不能产生多 primary_relation；
33. 候选通过后续正式内容和真实反馈验证；
34. Prompt 版本能够原子启用和回滚；
35. 开发者和用户都不需要手工撰写候选 Prompt。

最终目标不是让系统“更会写提示词”，而是：

> **先准确记录用户的认知边界，再准确识别每篇内容带来的认知变化，最后用真实反馈持续校准这套判断。**
