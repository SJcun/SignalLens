---
title: SignalLens 下一阶段升级方案
version: Draft V0.1
status: 未开始
date: 2026-08-18
---

# SignalLens 下一阶段升级方案

## 0. 结论

SignalLens 下一阶段不应优先扩展输入类型，也不应立即建设通用记忆框架、向量数据库或知识图谱。

当前最重要的升级，是把已经可用的“单篇内容分诊”推进为：

> **证据可追溯、结果可复盘、错误可归因，并能逐步识别认知增量的注意力投资决策系统。**

推荐顺序：

```text
真实评测基线
  ↓
不可变内容证据与完整分析快照
  ↓
判断复盘与忽略内容抽检
  ↓
Current User State
  ↓
Claims 与 Cognitive Delta
  ↓
经用户确认的 Cognitive Memory
  ↓
数据证明需要后再增加向量召回
```

近期只实施前三项。后续能力必须以前一阶段的真实评测结果为进入条件。

---

## 1. 当前基础与关键差距

项目已经具备可靠的单篇内容分诊基础：

- 网页采集、统一协议、内容身份与去重；
- 原始 Markdown 保存；
- `TriageContent → AnalyzeContent → EvaluateForUser` 三阶段分析；
- 结构化输出校验；
- 手动内容保护和高探索价值保护；
- Content Map、Claims、观点保真字段和章节级 Reading Plan；
- 显式用户画像；
- 阅读后反馈、AI 结果快照、校准矩阵和高价值误杀统计。

当前缺口不是“没有更多功能”，而是下面五个闭环尚未成立。

### 1.1 内容证据不可复现

同一 URL 重新采集时会更新原 `Content.markdown`，但旧分析只保存正文哈希，没有保留 AI 当时读取的原文版本。

结果是：旧分析和反馈无法完整还原，新正文也可能暂时继续关联旧分析结论。

### 1.2 判断快照不完整

现有反馈快照保存三阶段输出，但没有冻结：

- 当时的正文版本；
- 当时的用户画像与当前状态；
- 检索到的历史认知；
- 候选 Claims；
- 后续 Compare 阶段的输入。

系统只能知道“推荐错了”，还不能可靠回答“为什么错”。

### 1.3 用户画像仍然过于静态

当前画像不能清楚区分：

- 长期关注；
- 当前正在解决的问题；
- 临时兴趣；
- 已掌握的具体知识点；
- 当前接受、存疑和争议中的判断。

### 1.4 Claims 尚未成为历史证据

当前 Claims 只存在于分析 JSON 中，没有稳定身份、可靠来源引用，也没有进入历史比较。

因此现有 `novel_information` 更接近模型根据静态画像做出的推测，而不是经过历史证据支持的认知增量。

### 1.5 校准仍以统计为主

现有校准能够发现推荐偏高、偏低、摘要问题和高价值误杀，但尚未形成逐条错误归因，也没有把修正建议与具体判断证据关联起来。

---

## 2. 产品目标与硬约束

### 2.1 优化“阅读后是否值得”

系统主要预测：

> **用户投入精力消费内容后，是否会认为这次投入值得。**

点击、停留时长、播放完成度和收藏最多是弱信号，不能直接解释为内容价值或兴趣变化。

### 2.2 高价值漏判代价更高

相比多推荐一篇普通内容，错误过滤真正高价值内容的代价更高。

因此继续保持：

```text
不确定 → continue
```

并单独统计被建议忽略或摘要、但用户认为值得选择性阅读或精读的内容。

### 2.3 内容长度不降低价值等级

阅读价值与阅读成本必须分开：

```text
阅读价值
→ 决定 ignore / summary_enough / selective_read / deep_read

预计投入
→ 只描述成本和安排方式
```

一篇需要 60 分钟阅读的高价值文章，仍可得到 `deep_read`。`time_budget_minutes` 只应用于阅读安排，不直接进入价值等级判断。

### 2.4 反馈校准不等于兴趣学习

```text
“本次推荐准确”
≠
“以后多给我这个主题”
```

只有用户明确修改兴趣或当前目标时，才更新对应状态。

### 2.5 认知状态保持窄边界

SignalLens 只保存直接服务于阅读分诊的结构化认知，例如用户已掌握的知识点、当前判断及其来源。

不扩展为通用笔记、收藏、搜索、知识图谱或面向任意问题的 RAG 系统。

---

## 3. 目标流程

```text
Capture
  ↓
Content Identity
  ↓
Content Revision（不可变证据）
  ↓
TriageContent
  ↓
AnalyzeContent / Claims
  ↓
候选认知与证据检索
  ↓
CognitiveCompare
  ↓
CognitiveDelta
  ↓
EvaluateForUser + Current User State
  ↓
Recommendation / Reading Plan
  ↓
用户反馈
  ↓
Judgment Review
  ↓
认知或规则修改建议
  ↓
用户确认
```

阶段职责保持分离：

- `TriageContent`：保守快速门禁，不判断真实个人认知增量；
- `AnalyzeContent`：只理解内容本身，不读取完整用户状态；
- `CognitiveCompare`：比较当前 Claims 与历史认知证据；
- `EvaluateForUser`：结合 Cognitive Delta 和 Current User State 生成阅读建议；
- `Judgment Review`：反馈后分析本次判断哪里正确、哪里错误；
- 认知更新：只生成建议，必须由用户确认。

---

## 4. 核心数据语义

### 4.1 Content 与 Content Revision

`Content` 继续表示唯一内容身份：

```text
source_type + canonical_url
```

`ContentRevision` 表示某次实际采集到的不可变正文证据：

```text
id
content_id
source_hash
title
author
markdown
capture_payload_json
captured_at
```

规则：

- 相同 Content、相同 `source_hash`：保持幂等；
- 相同 Content、不同 `source_hash`：创建新 Revision 和新 Analysis；
- 旧 Revision、Analysis 和 Feedback 保持可复现；
- 创建 Revision 不改变内容唯一身份。

### 4.2 Analysis Run

现有 `Analysis` 演进为绑定 Revision 的分析运行记录，并冻结：

```text
content_revision_id
profile_snapshot_json
current_state_snapshot_json
retrieval_snapshot_json
model
prompt_version
schema_version
```

旧数据缺少上下文时标记为 legacy，不生成虚假快照。

### 4.3 Claim

Claim 是历史比较的最小证据单元：

```text
id
analysis_id
content_revision_id
claim_text
claim_type
verification
section_ref
importance
```

其中：

```text
claim_type:
fact / opinion / method / hypothesis / conclusion

verification:
supported_in_content / unverified / opinion
```

第一版只保存会影响理解和阅读决策的主要 Claims。

### 4.4 Current User State

建议区分：

```text
stable_interests       长期关注
active_topics          当前研究方向
active_questions       当前需要解决的问题
temporary_interests    临时兴趣
knowledge_items        明确掌握的知识点
reading_constraints    阅读安排约束
```

第一版全部由用户显式维护，不根据行为自动推断，也不自动过期。

### 4.5 Cognitive Delta

Cognitive Delta 表示新内容相对当前认知发生的变化：

```json
{
  "known": [],
  "new": [],
  "extends": [],
  "conflicts": [],
  "updates": [],
  "questions_created": [],
  "marginal_information_value": "low | medium | high"
}
```

每条 `new / extends / conflicts / updates` 都必须回溯到当前 Claim、来源章节及被比较的历史认知或 Claim。

### 4.6 Cognitive Memory

Cognitive Memory 只保存会影响未来阅读分诊、且经过用户确认的认知：

```text
statement
status: accepted / uncertain / disputed / obsolete
version
sources
confirmed_at
```

关系保持有限：

```text
supports / contradicts / extends / derived_from / replaces
```

不使用模型自报的精确小数置信度作为事实。优先记录状态、来源和是否确认。

### 4.7 Judgment Review

Judgment Review 由 Analysis 和 Feedback 产生：

```json
{
  "predicted_recommendation": "selective_read",
  "actual_recommendation": "deep_read",
  "outcome": "worthwhile",
  "knowledge_effect": "changed_understanding",
  "failure_type": "knowledge_state_gap",
  "explanation": "...",
  "suggested_correction": "...",
  "status": "pending_confirmation"
}
```

第一版错误类型保持有限：

```text
no_error
knowledge_state_gap
historical_duplicate_missed
important_delta_missed
cross_domain_value_missed
content_quality_overrated
length_bias
summary_omission
insufficient_evidence
```

---

## 5. 分阶段实施方案

## P0：真实评测基线与语义校正

### 目标

在扩展数据库和流水线前，先建立真实效果基线。

### 工作范围

1. 明确阅读价值与阅读成本分离；
2. 不将 `time_budget_minutes` 传入价值等级判断；
3. 将 Triage 的 `novelty_signal` 明确定义为“表面新颖性”；
4. 准备真实文章和文章组合；
5. 保存模型、Prompt、输入和输出，形成可重复运行的离线评测；
6. 暂不新增生产数据库表。

测试集至少覆盖：

- 长但高价值；
- 短但高度重复；
- 80% 重复、20% 重要新增；
- 同主题但核心观点冲突；
- 旧事实或版本更新；
- 低相关但高价值；
- 高质量但用户已完全掌握；
- 原文包含重要限制和不确定性。

### 验收门禁

- 内容长度不能单独导致推荐等级下降；
- 低相关高价值内容不能直接建议忽略；
- 80% 重复、20% 重要新增优先得到选择性阅读；
- 冲突和更新不能被当成重复过滤；
- 原文的重要限制、反方观点和未验证主张不能在摘要中消失；
- 评测结果可按 Prompt 与模型版本复现。

---

## P1：不可变证据与 Judgment Memory V1

### 目标

让每条反馈都能还原完整分析现场，并开始回答“为什么判断错”。

### 工作范围

1. 增加 `ContentRevision`；
2. `Analysis` 绑定 Revision；
3. 冻结画像、当前状态和模型输入快照；
4. 正文变化时创建新 Revision 和新 Analysis；
5. 增加低成本强反馈：“如果系统过滤了它，我是否会后悔？”；
6. 增加可选认知结果：没有新增 / 补充认识 / 改变认识 / 产生问题；
7. 反馈后生成 `JudgmentReview`；
8. 增加被建议忽略内容的抽检队列；
9. 只展示修正建议，不自动改 Prompt、画像或认知。

普通模式只保留：

```text
值得 / 部分值得 / 不值得
+
改变了我的认识（可选）
```

评测模式继续提供推荐等级、新知识量、摘要质量和关键收获。

### 验收门禁

- 相同正文不创建重复 Revision；
- 正文变化后旧分析仍能读取对应旧正文；
- 新正文不会继续展示旧正文分析结论；
- Judgment Review 能定位到 Analysis、Feedback 和 Revision；
- 反馈不会自动修改兴趣权重；
- 抽检能发现并统计错误忽略的高价值内容。

---

## P2：Current User State

### 进入条件

- P1 已能稳定保存完整判断快照；
- 真实反馈已经证明静态画像造成了具体误差。

### 工作范围

1. 在现有画像上补充当前状态；
2. 将“熟悉领域”升级为具体 `knowledge_items`；
3. 增加 `active_questions`；
4. 区分长期关注与临时兴趣；
5. 每次分析冻结 Current User State；
6. 全部由用户显式修改；
7. 不自动重算历史分析。

### 验收门禁

- “熟悉某主题”不能解释为“掌握全部知识”；
- 临时兴趣不能永久强化长期兴趣；
- 未明确声明的知识不能被模型当作事实；
- 阅读时间只影响安排，不影响价值等级。

---

## P3：Claims、CognitiveCompare 与 Cognitive Delta

### 进入条件

- 真实文章组合已经能稳定标注 `duplicate / extends / contradicts / updates / new`；
- Content Revision、分析快照和 Current User State 已稳定。

### 工作范围

1. 为主要 Claims 增加稳定身份和来源引用；
2. 先按主题、实体和少量已确认认知选择候选；
3. 新增 `CognitiveCompare` Prompt 和 Schema；
4. 生成 `CognitiveDelta`；
5. `EvaluateForUser` 消费 Cognitive Delta，不再自行猜测历史增量；
6. 推荐理由说明已知、新增、冲突、更新和建议阅读位置；
7. 详情页展示 Delta 和来源；
8. 暂不增加向量数据库。

关系枚举：

```text
duplicate / extends / complements / contradicts / updates / new / unrelated
```

### 验收门禁

- 每条关系都有当前 Claim 和历史证据；
- 高语义相似但结论相反时识别为 `contradicts`；
- 旧事实变化时识别为 `updates`；
- 整体重复但局部有重要新增时生成选择性阅读；
- 找不到证据时输出不确定，不伪造用户已知状态；
- Compare 阶段不能修改 Cognitive Memory。

---

## P4：Cognitive Memory V1

### 进入条件

- Cognitive Delta 在真实文章组合上达到可接受稳定性；
- 用户能够理解并核对 Delta 来源；
- 已证明认知状态能改善推荐，而不是增加随机误判。

### 工作范围

1. 保存用户确认过的认知；
2. 支持 accepted / uncertain / disputed / obsolete；
3. 保存来源和版本链；
4. 新内容和反馈只生成 CREATE / UPDATE / DISPUTE / OBSOLETE 建议；
5. 用户确认后才应用；
6. 冲突认知并存，不自动覆盖；
7. 检索时优先查 Cognitive Memory；
8. 需要证据、存在冲突或认知不明确时，再回溯 Claims 和 Content。

### 验收门禁

- 每条认知都有来源和版本；
- 用户可以拒绝修改建议；
- 冲突不会静默覆盖；
- 未确认建议不能参与正式分诊；
- 删除单一来源不会破坏仍有其他证据支持的认知。

---

## P5：候选召回扩展

只有出现以下可观测问题时才进入：

- 主题和实体检索频繁漏掉明显相关认知；
- 活跃 Claims 或 Cognitive Memory 已无法低成本比较；
- 模型输入成本成为主要瓶颈；
- 已有人工标注集可以评估召回率。

目标流程：

```text
topic / entity filter
  ↓
embedding candidate recall
  ↓
recency / importance
  ↓
LLM relation judgment
```

约束：

- Embedding 只负责候选召回；
- 向量相似度不能直接决定重复、冲突或更新；
- 首先验证 SQLite 下的简单实现；
- 只有规模、并发和运维数据支持时才评估迁移数据库；
- 不建设知识图谱或复杂 Agent 编排。

---

## 6. Prompt 与界面演进

### 6.1 Prompt 职责

`TriageContent`：

- 保持快速、保守；
- 不读取完整认知历史；
- 新颖性只代表内容表面信号。

`AnalyzeContent`：

- 继续只分析内容本身；
- 为 Claims 增加类型、`section_ref` 和关键证据；
- 继续保留限制、反方观点、不确定性和未验证主张。

`CognitiveCompare`：

- 输入 Current Claims、候选 Cognitive Memories 和候选历史 Claims；
- 输出 known / new / extends / conflicts / updates / questions_created；
- 不生成最终阅读建议，也不修改 Memory。

`EvaluateForUser`：

- 输入 Content Analysis、Cognitive Delta 和 Current User State；
- 输出推荐、解释、探索属性和 Reading Plan；
- 长度不能作为降级理由；
- 没有证据时不能声称用户已经知道。

### 6.2 Web 展示

P1 增加：

- 当前正文 Revision；
- 判断差异和错误原因；
- 忽略内容抽检；
- 后悔漏判和认知变化反馈。

P3 增加：

```text
你大概率已经知道
本文真正新增
对已有认识的补充
与已有认识的冲突
旧信息更新
产生的新问题
相关来源
```

Inbox 只显示简短原因，不放复杂关系图。

P4 增加认知修改建议、来源、接受 / 拒绝和版本历史，不提供知识图谱可视化。

---

## 7. 数据迁移原则

任何数据模型升级都必须先对实际 SQLite 创建可恢复备份，并使用临时数据库验证迁移。

推荐顺序：

1. 创建 `content_revisions`；
2. 为每条现有 Content 建立初始 Revision；
3. 复制当前 Markdown、采集载荷和哈希；
4. 为 Analysis 增加可空 `content_revision_id`；
5. 能确认正文哈希一致的 Analysis 关联对应 Revision；
6. 无法确认的旧 Analysis 标记为 legacy；
7. 先兼容读取，再把新写入切换到 Revision；
8. 不删除现有 Content、Analysis 或 Feedback；
9. Windows 测试中显式释放 SQLite 文件句柄。

旧分析缺少来源引用时，可以继续展示文章级建议和摘要，但不能启用依赖精确证据的新界面，也不能伪造旧画像或旧检索快照。

---

## 8. 评测指标

### 8.1 首要指标

高价值漏判：

```text
AI 建议 ignore / summary_enough
但用户确认 selective_read / deep_read
且 time_worthwhile = yes
```

后悔漏判：

```text
用户明确表示：如果被系统过滤，会后悔错过
```

这两个指标优先于整体准确率。

### 8.2 辅助指标

- 推荐四级混淆矩阵；
- 相邻偏差和严重偏差；
- 按文章长度分组的推荐偏差；
- Claims 来源引用完整率；
- 关系判断准确率；
- 候选召回率；
- Cognitive Delta 人工认可率；
- Cognitive Memory 修改建议接受率；
- 单篇分析模型调用次数与成本。

点击率、停留时间、阅读完成率和同主题内容消费数量只能辅助诊断交互，不能作为阅读价值指标。

---

## 9. 主要风险与控制

| 风险 | 控制方式 |
| --- | --- |
| 错误认知被反复放大 | 更新必须确认；保留来源与版本；冲突不覆盖 |
| 检索漏掉历史信息 | 单独评测候选召回；不足时输出不确定 |
| 反馈负担过高 | 普通模式只保留强反馈；详细问题仅在评测模式出现 |
| 产品膨胀为知识库 | 每项能力必须直接改善分诊、错杀率、选择性阅读或错误解释 |
| 基础设施提前复杂化 | Prompt 验证先于检索；默认 SQLite；没有数据不迁移 |

---

## 10. 明确不做

本轮升级不包括：

- PDF、音视频和 RSS Adapter；
- 通用 RAG；
- 知识图谱；
- 自动学习兴趣权重；
- 自动接受认知修改；
- 全量文章两两比较；
- 通用 Memory Framework；
- 多用户；
- 复杂推荐 Feed；
- 自动推送；
- 全功能收藏与知识管理。

这些能力只有在核心阅读分诊闭环通过真实使用验证后才重新评估。

---

## 11. 推荐的第一批实施任务

下一次进入代码实施时，只建议选择以下范围。

### 任务 1：评测语义与文章组合

```text
Prompt 硬约束
+
真实文章评测集
+
长度偏差测试
+
高价值漏判基线
```

### 任务 2：Content Revision

```text
ContentRevision 模型
+
Analysis 关联
+
重复正文幂等
+
正文变化创建新分析
+
迁移测试
```

### 任务 3：Judgment Review 与忽略抽检

```text
反馈强信号
+
错误类型
+
逐条差异整理
+
忽略内容抽检
+
校准统计
```

完成这三项后，应真实使用一段时间，再决定是否进入 Current User State 和 Cognitive Delta。

---

## 12. 总体验收条件

下一阶段完成不以“增加了 Memory 功能”作为标准，而以以下事实作为标准：

1. 任意分析都能还原当时的正文、用户状态、模型和 Prompt；
2. 正文变化不会继续展示旧正文的 AI 结论；
3. 用户反馈能够形成具体、可检查的错误原因；
4. 高价值漏判得到独立抽检和统计；
5. 内容长度不会成为降低阅读价值的理由；
6. 系统不会根据单次反馈自动强化兴趣；
7. 引入认知比较后，每条新增、冲突和更新都有来源；
8. 未经用户确认的认知修改不会进入后续正式判断；
9. 新能力仍服务于阅读分诊，而不是把项目扩展成通用知识库。

最终目标保持不变：

> **减少低价值和重复阅读，同时尽量避免错过真正值得投入注意力的内容。**
