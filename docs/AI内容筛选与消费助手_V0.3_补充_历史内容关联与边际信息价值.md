---
title: AI 内容筛选与消费助手 V0.3 补充 —— 历史内容关联与边际信息价值
version: V0.3-S1
status: V0.3 补充设计
date: 2026-08-13
---

# AI 内容筛选与消费助手 V0.3 补充

## —— 历史内容关联、观点级比较与边际信息价值

> 本文作为《AI 内容筛选与消费助手 V0.3——防信息茧房与认知多样性方案》的补充文档。
>
> 本次补充解决一个长期使用后必然出现的问题：**新文章即使本身质量高、符合人物画像，也可能与历史文章大量重复，因此不能继续按“单篇文章价值”直接判定为精读。**
>
> 系统需要从“这篇文章好不好”进一步升级为：
>
> **在用户已经读过这些内容以后，这篇文章还剩下哪些真正值得投入注意力的新价值？**

---

# 1. 为什么必须增加历史内容关联

现有 V0.3 已经能够从以下维度判断文章：

- 内容自身质量；
- 信息密度；
- 实践价值；
- 与人物画像的相关性；
- 与已有知识点的重叠；
- 新增信息；
- 探索价值；
- 观点多样性；
- 阅读建议。

但如果不进一步使用**历史文章本身**作为比较对象，就会产生一个明显问题。

例如：

```text
文章 A
- MCP 架构
- Host / Client / Server
- Tool Discovery
- Gateway 权限设计
- 企业实践案例
```

文章 B：

```text
文章 B
- MCP 架构
- Host / Client / Server
- Tool Discovery
- Caller Context
- Gateway 新案例
```

如果只单独分析 B：

```text
内容质量：高
信息密度：高
个人相关性：高
实践价值：高
```

系统很可能得到：

```text
recommendation = deep_read
```

但对于已经完整阅读过 A 的用户，这个结果并不合理。

B 中大量内容已经被 A 覆盖，真正有价值的可能只有：

- Caller Context；
- 新的 Gateway 案例。

因此正确判断应该是：

```text
文章整体质量：高
历史内容重叠：高
边际新增价值：中
最终建议：选择性阅读
```

---

# 2. 新增核心概念：边际信息价值

本项目正式增加：

> **边际信息价值（Marginal Information Value）**

它表示：

> **在扣除用户已经掌握的知识和历史内容已经覆盖的信息后，新内容仍然能够为用户带来的新增认知价值。**

可以用概念表达式理解：

```text
文章原始价值
- 已掌握知识
- 历史重复内容
+ 新观点
+ 新证据
+ 新案例
+ 对旧信息的更新
+ 与旧观点的冲突
=
边际信息价值
```

这里不是要求实现数学公式，而是用于指导 AI 判断。

以后产品最重要的问题不再只是：

> 这篇文章值得看吗？

而是：

> **在你已经看过这些内容以后，这篇文章还有哪些部分值得看？**

---

# 3. 历史内容不等于用户画像

后端必须明确区分三类上下文。

## 3.1 User Profile

描述用户当前关注和阅读目标：

```text
关注领域
当前项目
偏好
不喜欢的内容
阅读目标
基础能力
```

它回答：

> **这篇文章和用户现在的目标有关吗？**

---

## 3.2 Knowledge State

描述用户已经较稳定掌握的具体知识点。

例如：

```text
MCP Host / Client / Server 基础职责
MCP Tool 基础调用流程
Git rebase 基础用途
```

它回答：

> **这篇文章里的哪些知识用户大概率已经知道？**

知识状态必须尽量采用**知识点粒度**，而不是：

```text
用户懂 MCP
用户懂 Git
```

这种过于粗糙的主题级标签。

---

## 3.3 Content History

保存历史已经分析、阅读或确认有价值的具体内容。

例如：

```text
文章 A
文章 B
视频 C
Podcast D
```

每个历史内容需要保留：

- Content Map；
- Key Points；
- Claims；
- Section Analysis；
- 来源；
- 时间；
- 用户实际阅读状态；
- AI 当时的阅读建议。

它回答：

> **新内容和过去真正消费过的内容是什么关系？**

三者不能混为一谈。

---

# 4. 新的完整判断流程

V0.3 原有流程：

```text
PageSift
   ↓
TriageContent
   ↓
AnalyzeContent
   ↓
EvaluateForUser
   ↓
Reading Plan
```

补充后：

```text
PageSift
   ↓
TriageContent
   ↓
AnalyzeContent
   ↓
历史内容检索
   ↓
HistoricalCompare
   ↓
EvaluateForUser
   ↓
Marginal Value
   ↓
Reading Plan
```

更加完整地表示：

```text
                 新内容
                   │
        ┌──────────┴──────────┐
        ↓                     ↓
   User Profile          Content History
        │                     │
        ↓                     ↓
    当前相关性            历史覆盖程度
        │                     │
        └──────────┬──────────┘
                   ↓
             Knowledge State
                   ↓
        新增 / 重复 / 冲突 / 更新
                   ↓
             边际信息价值
                   ↓
      忽略 / 摘要 / 选择性阅读 / 精读
                   ↓
          章节级 skip / skim / deep
```

---

# 5. 不做“文章相似度判断”，而做“信息关系判断”

仅计算：

```text
文章 B 与文章 A 相似度 = 0.86
```

是不够的。

因为语义相似不代表信息重复。

例如：

```text
A：
Gateway 应集中负责所有授权。

B：
Gateway 不应该承担业务授权，
业务授权应该由下游 MCP Server 或业务系统处理。
```

两段内容在向量空间中可能高度相似。

但它们实际上属于：

```text
观点冲突
```

这类文章反而具有更高阅读价值。

因此历史关系不能只有：

```text
similar / not_similar
```

至少需要以下关系：

| relation | 含义 | 默认阅读影响 |
| --- | --- | --- |
| `duplicate` | 基本重复，没有明显新增内容 | 降低阅读优先级 |
| `extends` | 在已有内容上进一步扩展 | 提高相关章节价值 |
| `complements` | 从另一角度提供补充 | 保留阅读价值 |
| `contradicts` | 与历史观点明显冲突 | 提高认知价值 |
| `updates` | 更新旧事实、版本、数据或状态 | 高优先级 |
| `new` | 历史中基本没有出现 | 高边际价值 |

这套关系应同时用于：

- 文章级；
- 章节级；
- 观点级。

---

# 6. 技术实现：向量检索只负责“找候选”

第一版不建议让 LLM 对所有历史文章逐篇比较。

合理流程：

```text
新文章
  ↓
生成 Content Map / Key Points / Claims
  ↓
Embedding / Full-text Search
  ↓
找到 Top N 历史候选
  ↓
LLM 做观点级比较
```

Embedding 的职责仅是：

> **从大量历史内容里快速找到“可能相关”的候选文章。**

它不能直接决定：

```text
是否重复
是否冲突
是否扩展
```

这些关系由 `HistoricalCompare` 完成。

第一版候选数量可以保持较小，例如：

```text
Top 3 ～ Top 8
```

具体数量后续通过真实数据调整。

---

# 7. HistoricalCompare

建议新增独立分析阶段：

```text
HistoricalCompare
```

输入：

```text
Current Content Analysis
+
Related Historical Content[]
```

输出至少包括：

```json
{
  "overall_overlap": "low | medium | high",

  "related_contents": [
    {
      "content_id": "xxx",
      "title": "MCP Gateway 架构设计",
      "relation": "extends",
      "reason": "本文大部分基础架构与历史文章重复，但新增 Caller Context 传播机制。"
    }
  ],

  "repeated_information": [
    "Host / Client / Server 基础架构",
    "Gateway 基础权限职责"
  ],

  "new_information": [
    "Caller Context 传播机制",
    "版本校验机制"
  ],

  "contradictory_information": [
    {
      "current": "业务授权应下沉到业务系统",
      "historical": "Gateway 应统一负责授权",
      "source_content_id": "xxx"
    }
  ],

  "updated_information": [],

  "marginal_value": "low | medium | high"
}
```

---

# 8. 章节级历史比较

文章级重叠度不能直接决定最终阅读建议。

因为一篇文章可能：

```text
80% 重复
20% 极有价值
```

因此必须把历史比较下沉到章节。

例如：

```json
{
  "section": "Caller Context",

  "historical_overlap": "low",

  "relation": "new",

  "action": "deep_read",

  "reason": "过去相关内容主要覆盖 Gateway 权限职责，尚未出现 Caller Context 的具体传播设计。"
}
```

另一个章节：

```json
{
  "section": "MCP 基础架构",

  "historical_overlap": "high",

  "relation": "duplicate",

  "action": "skip",

  "reason": "该部分与历史文章《MCP Gateway 架构设计》的 Host / Client / Server 说明高度重复。"
}
```

最终 AI 才能真正生成：

```text
全文阅读需要 28 分钟
真正值得投入约 9 分钟
```

---

# 9. 阅读建议增加“边际价值”约束

以后不能只使用：

```text
质量高 + 相关性高
→ deep_read
```

应调整为：

```text
质量高
+
相关性高
+
边际信息价值高
→ deep_read
```

典型情况：

## 情况 A：高质量 + 高相关 + 高新增

```text
recommendation = deep_read
```

理由：

```text
与你当前目标高度相关，而且历史内容中尚未覆盖其核心机制。
```

---

## 情况 B：高质量 + 高相关 + 高重复

```text
recommendation = selective_read
```

理由：

```text
文章质量较高，但大量内容已经被历史内容覆盖，仅部分章节具有新增价值。
```

---

## 情况 C：高重复 + 存在明显冲突

不能：

```text
因为重复度高 → skip
```

而应该：

```text
recommendation = selective_read / deep_read
```

理由：

```text
虽然讨论主题与历史文章高度相似，但核心结论存在明显冲突，具有认知校正价值。
```

---

## 情况 D：旧信息被更新

例如：

```text
旧文章：
某 API 调用限制为 100 次。

新文章：
新版本调整为 50 次。
```

应识别：

```text
relation = updates
```

这种内容通常不需要全文阅读，但更新部分优先级很高：

```text
recommendation = selective_read
```

---

# 10. AI 总结必须解释“为什么”

历史比较加入以后，AI 输出不能只显示：

```text
选择性阅读
```

必须解释三件事：

## 10.1 为什么值得看？

例如：

```text
本文新增了 Caller Context 传播机制和一个新的企业部署案例。
```

## 10.2 为什么不用全文看？

例如：

```text
约三分之二核心内容与此前阅读的 MCP Gateway 文章重复。
```

## 10.3 应该重点看哪里？

例如：

```text
建议重点阅读第 4 节和第 6 节。
```

推荐理由建议最终形成固定结构：

```text
建议：选择性阅读

为什么：
本文与你当前关注的 MCP Gateway 高度相关，
但大部分架构说明与过去内容重复。

新增价值：
- Caller Context 的传播机制
- 版本校验机制
- 新的生产部署案例

不同观点：
- 本文认为业务权限不应全部集中在 Gateway

可跳过：
- MCP Host / Client / Server 基础架构
- Tool Discovery 基础流程

建议精读：
- 第 4 节
- 第 6 节
```

---

# 11. 内容详情页增加“与历史内容的关系”

建议在详情页新增独立模块：

```text
与历史内容的关系
```

示例：

```text
与历史内容重叠较高

最相关历史内容：

《MCP Gateway 架构设计》
阅读于 2026-08-03

重叠：
• MCP 基础架构
• Gateway 权限职责
• Tool Discovery

新增：
• Caller Context
• 版本校验机制

冲突：
• 业务授权是否应该集中在 Gateway

因此：
建议选择性阅读，而不是全文精读。
```

用户可以点击历史文章，查看具体关联。

---

# 12. 推荐结果增加关联理由

未来 Inbox 中也不建议只展示：

```text
推荐精读
```

可以增加简短解释，例如：

```text
选择性阅读

与 2 篇历史内容高度重叠，
但第 4、6 节包含新内容。
```

或者：

```text
推荐精读

主题虽然熟悉，
但本文观点与过去阅读明显冲突。
```

或者：

```text
摘要即可

核心结论已被过去 4 篇文章覆盖，
仅有少量案例更新。
```

这样用户在列表页就能理解 AI 判断。

---

# 13. 数据模型补充

建议增加内容关联表。

## content_relations

```text
id
source_content_id
target_content_id

relation
overlap_level

summary

repeated_points JSON
new_points JSON
contradictory_points JSON
updated_points JSON

created_at
```

其中：

```text
relation:
duplicate
extends
complements
contradicts
updates
new
```

---

## section_relations

第一版可以不单独建表，先保存在分析 JSON 中。

例如：

```json
{
  "section_id": "section-4",
  "historical_overlap": "low",
  "relation": "new",
  "related_content_ids": ["xxx"],
  "reason": "..."
}
```

真实使用后，如果需要查询、统计、可视化，再拆表。

---

# 14. EvaluateForUser 补充字段

建议 V0.3 的 `EvaluateForUser` 增加：

```json
{
  "historical_comparison": {
    "overall_overlap": "high",

    "related_contents": [
      {
        "content_id": "xxx",
        "title": "MCP Gateway 架构设计",
        "relation": "extends"
      }
    ],

    "repeated_information": [],

    "new_information": [],

    "contradictory_information": [],

    "updated_information": []
  },

  "marginal_information_value": "medium",

  "recommendation": "selective_read",

  "recommendation_reason":
    "整体与历史内容重叠较高，但两个章节包含重要新增信息，因此建议选择性阅读。"
}
```

---

# 15. 与防信息茧房机制的关系

历史重复检测不能变成新的过滤陷阱。

必须明确：

```text
重复主题 ≠ 没有价值
```

尤其以下情况不能因为“相似度高”被降权：

## 观点冲突

```text
contradicts
```

不同观点本身具有认知拓展价值。

---

## 新证据

同一个观点出现更可靠的数据、论文或案例：

```text
complements / extends
```

仍然值得阅读。

---

## 信息更新

时间敏感内容发生变化：

```text
updates
```

应该主动提高优先级。

---

## 旧主题中的新机制

即使主题完全相同：

```text
MCP
```

只要出现过去没有覆盖的具体机制：

```text
new
```

仍然属于高边际价值。

因此系统真正要减少的是：

> **重复认知消费**

而不是：

> **重复主题。**

---

# 16. 第一版实现边界

历史关联第一版不需要做成完整知识图谱。

建议只实现：

1. 保存每篇文章的 `Content Map / Key Points / Claims`；
2. 为历史内容建立 Embedding；
3. 新内容分析后检索 Top N 相关历史内容；
4. 通过 LLM 做 `HistoricalCompare`；
5. 生成文章级重复 / 新增 / 冲突 / 更新关系；
6. 为重要章节生成章节级历史比较；
7. 将历史关系写入推荐理由；
8. 在详情页展示最相关的历史内容。

第一版暂时不做：

- 全局知识图谱；
- 所有文章之间全量两两关联；
- 自动合并知识节点；
- 自动修改用户知识状态；
- 复杂 GraphRAG；
- 跨用户知识关联。

---

# 17. 推荐开发顺序

## 阶段 1：先验证 Prompt

选取真实文章组合：

```text
A：基础文章
B：大部分重复 + 少量新增
C：同主题但观点冲突
D：旧信息更新
E：完全新内容
```

检查 AI 能否稳定判断：

```text
duplicate
extends
contradicts
updates
new
```

---

## 阶段 2：历史候选检索

实现：

```text
Content Analysis
↓
Embedding
↓
Top N Historical Candidates
```

先不追求复杂召回。

目标只是：

> 不要漏掉最明显的历史相关文章。

---

## 阶段 3：HistoricalCompare

增加独立 Prompt 和 JSON Schema。

重点测试：

- 高相似但观点相反；
- 内容重复但案例不同；
- 同主题但版本更新；
- 文章整体重复但单章节有新价值。

---

## 阶段 4：合入 EvaluateForUser

最终推荐必须同时考虑：

```text
相关性
知识重叠
历史重叠
新增信息
观点冲突
探索价值
边际信息价值
```

---

## 阶段 5：UI

最后再增加：

```text
与历史内容的关系
新增信息
重复内容
不同观点
阅读理由
```

---

# 18. 验收标准

历史关联能力上线前至少验证以下指标。

## 18.1 重复内容识别

对于明显大量重复的文章：

```text
AI 不应继续频繁推荐全文精读。
```

---

## 18.2 新增内容保留

对于：

```text
80% 重复 + 20% 重要新增
```

系统必须能够：

```text
选择性阅读
```

而不是：

```text
直接忽略
```

---

## 18.3 冲突观点保护

对于高度相似但结论相反的文章：

```text
不能因为向量相似度高而降权。
```

系统应明确指出：

```text
观点冲突
```

并说明冲突位置。

---

## 18.4 更新信息识别

对于时间敏感信息发生变化：

```text
旧事实
→
新事实
```

系统必须能够识别：

```text
updates
```

---

## 18.5 推荐解释性

任何因为历史内容而改变的阅读建议，都必须能够回答：

```text
为什么改变？
和哪些历史内容相关？
哪里重复？
哪里新增？
哪里冲突？
最终建议看哪里？
```

---

## 18.6 边际阅读价值

最终目标不是提高“相似内容过滤率”，而是：

> **让用户减少重复阅读，同时不漏掉旧主题中的新知识、新证据、新观点和新变化。**

---

# 19. 对产品定位的进一步修正

普通 AI 总结工具解决：

> 这篇文章讲什么？

AI 阅读分诊解决：

> 这篇文章值得我读吗？

加入历史关联以后，产品真正解决的是：

> **在我已经读过这么多内容以后，这篇文章还有哪些部分值得我继续花时间？**

因此项目的长期核心能力可以进一步概括为：

```text
Capture
↓
Understand
↓
Compare
↓
Evaluate
↓
Triage
↓
Read
```

其中 `Compare` 将成为非常关键的一层。

它负责让系统从：

> **单篇内容分析器**

真正成长为：

> **长期个人信息消费助手。**

---

# 20. 核心原则补充

V0.3 已经确定：

> **减少信息噪音，但不减少认知边界。**

本补充文档再增加一条：

> **减少重复阅读，但不遗漏重复主题里的新增价值。**

最终两条原则共同约束推荐系统：

1. **减少信息噪音，但不减少认知边界。**
2. **减少重复阅读，但不遗漏新观点、新证据、新案例和新变化。**

这两条原则应该共同进入后续 Prompt、数据结构、UI 和验收标准。
