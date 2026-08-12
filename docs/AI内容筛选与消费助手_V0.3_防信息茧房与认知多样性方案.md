---
title: AI 内容筛选与消费助手 V0.3 —— 防信息茧房与认知多样性方案
version: V0.3
status: 开源项目整合 + 防信息茧房机制后的开发方案
date: 2026-08-12
---

# AI 内容筛选与消费助手 V0.3

## —— 结合 GitHub 开源项目，并加入防信息茧房与认知多样性机制

> 本文是在 V0.2 方案基础上，继续结合现有 PageSift 能力、GitHub 相近开源项目，并针对“AI 筛选是否会制造信息茧房”这一风险重新修订后的第三版方案。
>
> 核心结论仍然不变：**AI 总结不是最终产品，真正要解决的是“哪些内容值得占用我的注意力，以及值得我看哪一部分”。**
>
> V0.3 新增一个同等重要的约束：**减少信息噪音，但不减少认知边界。**
>
> 因此，AI 不能简单学习“用户喜欢什么，然后只给更多类似内容”，而应该同时优化两件事：**阅读效率**与**认知多样性**。

---


## 0. 文档说明与调研口径


本版方案基于三类事实重新收敛：

1. **现有 PageSift 能力**：网页正文提取、质量判断、Markdown / JSON 输出、Memento 接入等已经完成，因此新项目不再重复做 Web 内容清洗层。
2. **GitHub 开源项目验证**：已核查 Newscrux、Summarize、Karakeep、Readability Reader、Papr、AI Video Transcriber、Trove AI、Recally 的公开仓库 README 与项目说明。
3. **信息茧房风险**：AI 阅读分诊如果只根据“相关性、兴趣和历史反馈”优化，可能把用户已经熟悉的领域越推越窄，并压低跨领域信息、反方观点和真正的新知识。

本次修订的目的不是推翻 V0.2，而是回答四个问题：

- 哪些基础能力已经被别人证明可行，不值得再次探索；
- 哪些产品范式可以直接借鉴；
- 哪些能力应该成为本项目自己的核心差异；
- 如何让 AI 帮用户减少低价值信息，同时不把用户封闭在已有兴趣和认知里。

**V0.3 的四个重要调整：**

1. 深度分析前仍保留 `TriageContent` 快速分诊层；
2. `低相关性` 不再等同于 `低阅读价值`，新增 `exploration_value` 与 `perspective_diversity`；
3. 手动通过 PageSift 提交的内容不允许因为“与画像不相关”而被静默丢弃；
4. 用户反馈默认用于校准“AI 判断是否准确”，而不是简单提高某个主题的推荐权重。

多模态输入仍保持为未来独立 Adapter；知识库、RAG、知识图谱继续留给 Memento 或后续系统，不扩进 AI 阅读中心。

# 1. 结论先行


这个产品不应该做成：

```text
网页 / 视频 / PDF
        ↓
      AI 总结
        ↓
      结束
```

因为“总结”本身已经成熟，也很容易被通用 AI 产品覆盖。

更合理的产品定位是：

> **AI 阅读分诊（AI Reading Triage）+ 内容消费助手。**

完整逻辑：

```text
大量网络内容
    ↓
内容采集
    ↓
AI 第一轮阅读
    ↓
快速分诊
    ↓
┌─────────────┬─────────────┬─────────────┬─────────────┐
│ 可以忽略     │ 摘要即可     │ 选择性阅读   │ 全文精读     │
└─────────────┴─────────────┴─────────────┴─────────────┘
                              ↓
                       哪些章节值得看？
                              ↓
                    跳过 / 浏览 / 精读
                              ↓
                        用户实际消费
                              ↓
                           反馈
```

产品真正优化的是：

```text
人的注意力
```

而不是：

```text
文章长度
```

但 V0.3 增加第二个同等重要的目标：

```text
阅读效率
+
认知多样性
```

系统不能简单采用：

```text
和我越相关
→ 越值得看
```

因为真实情况可能是：

```text
相关性低
+
内容质量高
+
我以前几乎没有接触
+
可能拓展认知边界
=
值得探索
```

因此，**“阅读动作”与“探索属性”分开建模**：

```text
recommendation:
ignore / summary_enough / selective_read / deep_read

discovery_type:
profile_match / adjacent / outside_profile_high_value
```

一篇“与你当前画像关系较低”的文章，仍然可能被判断为：

```text
recommendation = selective_read
discovery_type = outside_profile_high_value
```

V0.3 的产品原则正式增加一句：

> **减少信息噪音，但不减少认知边界。**

# 2. 为什么结合开源项目后更确认这个方向

本次重点参考以下项目：

| 项目 | 主要定位 | 对本项目的启发 |
|---|---|---|
| [Newscrux](https://github.com/alicankiraz1/newscrux) | AI 新闻聚合、相关性过滤、结构化摘要 | **先筛选，再投入后续分析** |
| [Summarize](https://github.com/steipete/summarize) | Web / PDF / YouTube / Podcast / Audio / Video 统一总结 | **多模态输入层统一抽象** |
| [Karakeep](https://github.com/karakeep-app/karakeep) | 自托管收藏、AI 标签/总结、搜索、阅读 | **内容 Inbox、状态管理、阅读生命周期** |
| [Readability Reader](https://github.com/ldenoue/readability-read-aloud-web-pdf-ai-summary) | 本地优先文章/PDF/YouTube 阅读器 + AI 摘要 | **PDF、YouTube、本地处理和阅读器体验** |
| [Papr](https://github.com/l0ng-ai/papr) | 本地 RSS 阅读器 + Agent CLI | **未来 RSS 自动输入和自动 triage** |
| [AI Video Transcriber](https://github.com/wendy7756/AI-Video-Transcriber) | YouTube/B站/Podcast/音视频转录与总结 | **未来音视频输入管线** |
| [Trove AI](https://github.com/weaiw/trove-ai) | 中文互联网稍后读 + AI 知识库 | **长期知识体系，但同时提醒避免功能膨胀** |
| [Recally](https://github.com/recally-io/recally) | 内容捕获、AI 摘要、标签、搜索、知识管理 | **Capture → Organize → Rediscover 的完整生命周期** |

这些项目已经证明很多基础问题并不需要重新探索：

- 网页、PDF、YouTube、Podcast、音视频可以被统一成文本/结构化内容。
- AI 在正式总结之前做 relevance filter 是可行的。
- 内容 Inbox、标签、全文搜索、稍后读已经有成熟产品范式。
- RSS 可以成为未来自动内容流入口。
- 视频和播客的合理处理方式是 transcript-first，没有字幕时再进入 ASR。

因此，我们没有必要重复做一个“功能齐全的 AI 阅读器”。

真正应该自己做好的是：

```text
Understand
    ↓
Evaluate
    ↓
Triage
    ↓
Reading Plan
```

---

# 3. 与现有 PageSift 的关系

PageSift 已经是这个系统非常好的 Web 输入层。

现有 PageSift 已具备：

- 自动正文提取；
- 站点适配器；
- Readability / Defuddle / Semantic DOM 等引擎回退；
- 手动选区和区域提取；
- 页面清理与 URL 规范化；
- Markdown 转换；
- YAML Front Matter；
- 元数据识别；
- 内容质量判断；
- 结构化 JSON；
- 图片归档；
- Memento 收藏与待分析标记。

因此，新系统**不重新实现网页采集**。

职责划分：

```text
PageSift
负责 Capture

AI 阅读中心
负责 Understand / Evaluate / Triage / Consume

Memento
负责真正值得长期保存的内容与认知沉淀
```

推荐形成：

```text
Web
 ↓
PageSift
 ↓
AI 阅读中心
 ↓
这篇内容真的有长期价值？
 ↓ 是
Memento
```

这样可以避免：

```text
看到 → 收藏 → 永远不看
```

而变成：

```text
看到
 ↓
AI 初筛
 ↓
自己阅读有价值部分
 ↓
确认有长期价值
 ↓
再进入 Memento
```

---

# 4. 从 GitHub 项目中具体借鉴什么

## 4.1 Newscrux：借鉴“先分诊，再总结”

Newscrux 的关键不是摘要，而是其处理顺序：

```text
RSS
 ↓
相关性判断
 ↓
低相关 → 丢弃
 ↓
高相关
 ↓
获取全文
 ↓
结构化总结
```

这给本项目带来的最大调整是：

> **不要所有文章一进来就立即运行最昂贵、最完整的深度分析。**

V0.2 将分析拆成：

```text
Triage
 ↓
值得进一步处理？
 ↓
Analyze
 ↓
EvaluateForUser
 ↓
ReadingPlan
```

Newscrux 的结构化摘要还使用了类似：

- What happened
- Why it matters
- Key detail

这种输出方式说明：相比一整块“摘要”，**带明确问题的结构化结果更有用**。

### 我们不照搬的部分

- 不使用单纯 1～10 的相关性评分作为最终决策。
- 不把产品局限在 RSS/新闻。
- 不只根据主题相关性，而是进一步判断用户是否已经知道这些内容。

---

# 5. Summarize：借鉴统一输入架构

Summarize 已经把以下内容统一进入同一套处理流程：

```text
Web
PDF
Image
Text File
YouTube
Podcast
Audio
Video
Video Slides
```

其中媒体内容采用 transcript-first：

```text
存在字幕 / Transcript
        ↓
    优先直接使用

不存在
        ↓
      ASR
```

视频还可以进一步提取场景帧、OCR 和时间戳。

这说明未来的 AI 阅读中心不应该围绕：

```text
Article
```

设计数据模型。

应该围绕：

```text
Content
```

设计。

建议统一数据结构：

```json
{
  "source_type": "web | pdf | youtube | bilibili | podcast | audio | video",
  "title": "...",
  "source_url": "...",
  "author": "...",
  "content": "...",
  "sections": [],
  "duration_seconds": null,
  "metadata": {},
  "capture": {}
}
```

第一版 `source_type` 只有：

```text
web
```

但上层分析服务不要写死为 `article`。

---

# 6. Karakeep：借鉴 Inbox，而不是复制知识库

Karakeep 已经覆盖了非常多成熟的“稍后读”能力：

- 收藏网页、图片、PDF；
- 自动抓取标题、描述、图片；
- 列表；
- 全文搜索与语义搜索；
- AI 自动标签与摘要；
- 浏览器扩展；
- 手机端；
- 离线阅读；
- RSS 自动收藏；
- Highlight；
- 全页归档；
- 视频归档；
- API；
- 自托管。

所以 AI 阅读中心没有必要重新证明这些产品形态。

值得借鉴的是它的内容生命周期：

```text
Inbox
 ↓
Processing
 ↓
Read / Archived / Organized
```

映射到我们的产品：

```text
Inbox
 ↓
AI 分诊
 ↓
推荐精读 / 摘要即可 / 可以忽略
 ↓
用户确认
 ↓
已消费
```

### V0.1 不做

- 复杂收藏夹；
- 多级标签系统；
- 语义搜索；
- 协作；
- 完整知识库；
- 自动归档整个互联网内容。

这些能力已经不是核心差异。

> 注意：Karakeep 使用 AGPL-3.0。V0.1 只参考产品与架构思路，不直接复制其代码，避免不必要的许可边界复杂化。

---

# 7. Readability Reader：确认 PageSift 的方向正确

Readability Reader 与 PageSift 在底层能力上有明显重叠：

- Manifest V3 浏览器扩展；
- Mozilla Readability；
- Defuddle 站点提取；
- PDF；
- YouTube Transcript；
- 本地 AI 摘要；
- 最近阅读库；
- 搜索；
- TTS。

它对我们最大的意义不是“照着做”，而是证明：

```text
Readability
+
Defuddle
+
站点特殊处理
```

是一条合理的工程路线。

### 后续可重点研究

1. PDF.js 的本地 PDF 内容解析。
2. YouTube Captions / Chapters 到结构化 Transcript 的方式。
3. 本地模型摘要是否适合作为隐私模式。
4. 阅读页面中的段落级高亮与 TTS。

### 当前不做

AI 阅读中心 V0.1 不开发完整阅读器，也不做 TTS。

PageSift + 原网页已经足够验证阅读分诊核心。

---

# 8. Papr：未来自动内容流的参考

Papr 的价值在于：

```text
RSS Reader
+
Agent-facing CLI
```

Agent 可以：

- read；
- search；
- triage；
- mark；
- extract；
- refresh。

这非常适合成为未来版本的参考：

```text
V0.1
用户看到文章 → 手动 PageSift → AI 分析
```

升级为：

```text
V0.3
RSS / 关注来源
      ↓
自动进入 Inbox
      ↓
AI 自动第一轮分诊
      ↓
每天只展示真正值得看的内容
```

但自动信息流不能出现在第一版，否则产品会同时变成：

```text
RSS Reader + AI Reader + Knowledge Base
```

范围会立即失控。

---

# 9. AI Video Transcriber：音视频不需要从零设计

AI Video Transcriber 已经覆盖：

- YouTube；
- Bilibili；
- TikTok；
- Apple Podcasts；
- SoundCloud；
- 30+ 媒体平台；
- 本地音频；
- 本地视频；
- FFmpeg；
- Whisper 类转录；
- 多语言总结；
- OpenAI-compatible 模型。

未来的媒体输入层可以按以下方式设计：

```text
URL / File
   ↓
yt-dlp / platform extractor
   ↓
已有字幕？
   ├─ 是 → Transcript
   └─ 否 → Audio → ASR → Transcript
   ↓
Topic Segmentation
   ↓
Unified Content
```

然后直接复用现有阅读分诊：

```text
Transcript
 ↓
Content Map
 ↓
哪些时间段值得听/看？
 ↓
skip / skim / deep_watch
```

例如：

```text
视频总长：83 分钟

00:00–12:30  基础介绍     → 跳过
12:30–21:45  Agent Memory → 精看
21:45–37:20  闲聊         → 跳过
37:20–52:40  MCP Gateway  → 精看
```

这才是音视频真正有价值的扩展，而不是只生成一段视频摘要。

---

# 10. Trove AI / Recally：提醒我们不要做成“大而全知识库”

Trove AI 和 Recally 都进一步走向：

```text
Capture
 ↓
AI Processing
 ↓
Search
 ↓
Knowledge Management
 ↓
Related Content / RAG / Knowledge Graph
```

这些能力本身都很有价值。

但是对本项目而言，它们最大的启发反而是：

> **V0.1 必须严格控制边界。**

因为只要开始加入：

- 知识图谱；
- RAG；
- 向量数据库；
- 相关内容；
- 学习路径；
- Obsidian 同步；
- Agent；

项目就会迅速从：

```text
AI 阅读分诊
```

变成：

```text
又一个个人知识管理平台
```

而长期知识沉淀已有 Memento 承担。

因此 AI 阅读中心应该刻意停在：

```text
内容进入
→ 判断价值
→ 辅助消费
→ 用户决定是否沉淀
```

---

# 11. V0.3 修订后的系统分层


```text
┌───────────────────────────────────────┐
│            Source Layer               │
│ Web / PDF / YouTube / Bilibili / ... │
└───────────────────┬───────────────────┘
                    │
                    ▼
┌───────────────────────────────────────┐
│           Capture Adapter             │
│ Web → PageSift                        │
│ PDF → Future PDF Adapter              │
│ Media → Future Media Adapter          │
└───────────────────┬───────────────────┘
                    │
                    ▼
┌───────────────────────────────────────┐
│           Unified Content             │
│ metadata / content / sections         │
└───────────────────┬───────────────────┘
                    │
                    ▼
┌───────────────────────────────────────┐
│              AI Triage                │
│ relevance / signal / exploration      │
│ 快速判断是否值得进一步处理            │
└──────────────┬────────────────────────┘
               │
       ┌───────┴──────────────┐
       │                      │
       ▼                      ▼
低价值 / 高重复           值得进一步分析
       │                      │
       ▼                      ▼
 保留可回看状态      ┌──────────────────────┐
                     │   Analyze Content     │
                     │ Summary / Map / Claim │
                     │ Counterpoint / Limits │
                     └──────────┬───────────┘
                                │
                                ▼
                     ┌──────────────────────┐
                     │ Evaluate For User    │
                     │ Novelty / Relevance  │
                     │ Exploration / Diversity│
                     └──────────┬───────────┘
                                │
                                ▼
                     ┌──────────────────────┐
                     │ Reading Plan         │
                     │ skip / skim / deep   │
                     └──────────┬───────────┘
                                │
                                ▼
                     ┌──────────────────────┐
                     │ Feedback             │
                     │ 判断准确性 / 行为     │
                     └──────────┬───────────┘
                                │
                                ▼
                         Optional Memento
```

V0.3 对这条链路增加两条硬约束：

1. **手动 Capture 代表明确用户意图。** 用户主动通过 PageSift 提交的文章，即使画像相关性低，也不能被后台静默删除或彻底隐藏。
2. **低相关不等于低价值。** `TriageContent` 必须同时观察文章自身信号、新颖性和探索价值，而不能只做兴趣匹配。

# 12. 三阶段分析流程：从相关性筛选升级为价值分诊


V0.1 原方案是：

```text
AnalyzeContent
      ↓
EvaluateForUser
```

V0.2 增加了前置分诊：

```text
TriageContent
      ↓
AnalyzeContent
      ↓
EvaluateForUser
```

V0.3 不增加第四个模型阶段，而是**修正这三个阶段的目标**，让它们不把“兴趣匹配”误当成“价值判断”。

## 12.1 TriageContent

目标：

> 快速判断是否值得继续投入模型计算和用户注意力，但不负责替用户封锁信息。

输入：

- title；
- source；
- source_type；
- capture mode（manual / automatic）；
- PageSift quality；
- markdown；
- 简单用户关注主题。

建议输出：

```json
{
  "relevance": "low | medium | high | very_high",
  "intrinsic_signal": "low | medium | high",
  "novelty_signal": "low | medium | high | unknown",
  "exploration_value": "low | medium | high",
  "discovery_type": "profile_match | adjacent | outside_profile_high_value",
  "decision": "ignore | continue",
  "reason": "...",
  "why_outside_profile": null
}
```

约束：

- `Triage` 只是快速门禁，不产生最终阅读建议；
- **不能因为 `relevance = low` 单独做出 `ignore`**；
- 手动 PageSift Capture 默认视为强用户意图，除非提取失败或内容明显无效，否则至少保留并允许完整分析；
- `ignore` 只用于“低信号 + 高重复/低质量 + 缺少明显探索价值”等组合情况；
- 不确定时：

```text
continue
```

而不是：

```text
ignore
```

- 被判断为 `ignore` 的内容仍保留在可回看的状态中，不做不可逆删除。

## 12.2 AnalyzeContent

这一阶段只分析内容本身，不读取完整用户画像。

基础输出：

- one_sentence_summary；
- summary；
- content_profile；
- content_map；
- key_points；
- claims；
- section summaries。

V0.3 新增“观点保真”要求。对于观点型、论证型、争议型内容，尽量结构化提取：

```json
{
  "thesis": "...",
  "supporting_evidence": [],
  "counterarguments": [],
  "author_stance": "...",
  "unresolved_questions": [],
  "unverified_claims": []
}
```

目的不是让 AI 强行制造“正反两面”，而是：

> **如果原文确实存在反方观点、限制条件、争议或不确定性，摘要不能把它们压缩掉。**

## 12.3 EvaluateForUser

输入：

```text
AnalyzeContent
+
User Profile
+
可选历史反馈
```

输出：

- relevance；
- knowledge_overlap；
- known_or_redundant；
- novel_information；
- exploration_value；
- perspective_diversity；
- discovery_type；
- recommendation；
- recommendation_reason；
- why_outside_profile；
- reading_plan。

这里明确区分：

```text
“我是否熟悉这个主题”
```

与：

```text
“这篇文章是否有价值”
```

即使：

```text
relevance = low
```

只要：

```text
exploration_value = high
```

仍然可以得到：

```text
recommendation = selective_read
```

或：

```text
recommendation = deep_read
```

# 13. 文章级阅读建议


保留四种“阅读动作”：

| 机器值 | 用户显示 | 使用场景 |
|---|---|---|
| `ignore` | 可以忽略 | 低价值、高重复、明显无效 |
| `summary_enough` | 摘要即可 | 只需要知道事实或结论 |
| `selective_read` | 选择性阅读 | 只有部分章节真正有价值 |
| `deep_read` | 全文精读 | 整篇持续高价值 |

其中最重要的是：

```text
selective_read
```

因为真实网络内容往往不是：

```text
整篇有价值 / 整篇没价值
```

而是：

```text
某 20%～40% 特别值得看
```

V0.3 不把“探索”设计成第五种阅读动作，而是单独增加发现属性：

| 机器值 | 用户显示 | 含义 |
|---|---|---|
| `profile_match` | 高度相关 | 与当前关注和知识目标直接相关 |
| `adjacent` | 邻近探索 | 与已有兴趣有连接，但超出当前核心范围 |
| `outside_profile_high_value` | 认知探索 | 与画像关系较低，但自身质量、新颖性或跨领域价值较高 |

这样可以避免把：

```text
“与我不相关”
```

错误地等价成：

```text
“不值得看”
```

例如：

```text
文章建议：选择性阅读
发现属性：认知探索

原因：
与你当前技术主题关联较低，但文章讨论确认偏误与信息筛选，
可能帮助你反思自己如何判断技术观点。
```

# 14. 章节级阅读计划

每个 Content Section 生成：

```json
{
  "section_id": "...",
  "title": "...",
  "summary": "...",
  "importance": "low | medium | high",
  "novelty": "known | partial | new",
  "action": "skip | skim | deep_read",
  "reason": "...",
  "estimated_minutes": 4
}
```

用户最终看到：

```text
完整阅读预计：35 分钟
推荐实际投入：12 分钟

第 1 节 → 跳过
第 2 节 → 跳过
第 3 节 → 浏览
第 4 节 → 精读
第 5 节 → 精读
```

这种结果比“本文摘要如下”更接近产品核心价值。

---

# 15. 用户画像第一版仍然保持极简


第一版仍然不构建自动知识图谱，也不要求系统“知道用户的一切”。

但 V0.3 修正一个重要问题：

> **不能用“用户知道 MCP / Git / Agent”这种粗粒度标签，代表用户已经掌握整个主题。**

因为这会导致系统把同一主题内真正新的内容也误判为重复。

第一版建议保留兴趣主题，同时把“已有基础”尽量记录到知识点层级：

```json
{
  "interests": [
    "AI Coding",
    "Agent",
    "MCP",
    "LLM",
    "Git",
    "软件架构"
  ],
  "knowledge_items": [
    {
      "concept": "MCP Host / Client / Server 基础职责",
      "state": "known",
      "confidence": "high",
      "source": "manual"
    },
    {
      "concept": "Git rebase 基础用途",
      "state": "known",
      "confidence": "medium",
      "source": "manual"
    }
  ],
  "avoid": [
    "营销推广",
    "低质量转载",
    "重复基础内容"
  ],
  "goal": "保持前沿"
}
```

如果第一版 UI 不想做这么细，也可以继续展示主题级熟悉度，但后端不要把：

```text
topic = MCP
level = intermediate
```

解释成：

```text
所有 MCP 内容都已知
```

而只把它当作一个弱先验。

同时，用户画像需要区分：

```text
兴趣偏好
```

和：

```text
知识状态
```

两者不能混成同一个推荐权重。

# 16. 反馈闭环


借鉴推荐系统思路，但第一版不要做复杂在线学习。

用户只需要极低成本反馈：

```text
AI：推荐精读

👍 判断准确
👎 判断不准确
```

或：

```text
AI：可以忽略

✓ 确实没价值
! 其实值得看
```

V0.3 对反馈语义增加一个非常重要的限制：

> **“判断准确”默认表示这一次阅读建议准确，不等于“以后给我更多这个主题”。**

也就是说：

```text
👍 推荐准确
```

不能直接被转换成：

```text
Agent 兴趣权重 +10
```

否则系统会出现典型的自我强化：

```text
推荐 Agent
→ 用户认可
→ Agent 权重更高
→ 推荐更多 Agent
→ 用户接触其他领域越来越少
```

建议保存：

```json
{
  "content_id": "...",
  "analysis_id": "...",
  "ai_recommendation": "selective_read",
  "recommendation_accuracy": "accurate",
  "final_action": "read",
  "topic_preference_signal": null,
  "created_at": "..."
}
```

只有用户明确执行类似：

```text
“以后多推荐这个主题”
```

时，才更新兴趣偏好。

未来如果引入自动画像学习，也必须把：

```text
recommendation calibration
```

与：

```text
interest preference learning
```

拆成两套机制。

# 17. PageSift V0.1 改造范围


PageSift 不做大改。

只增加：

```text
✨ AI 分析
```

流程：

```text
当前网页
 ↓
PageSift 已有提取
 ↓
用户主动点击 AI 分析
 ↓
POST /api/contents/analyze
 ↓
返回 Quick Triage
 ↓
Popup 显示：
推荐精读 / 摘要即可 / 选择性阅读 / 可以忽略
 ↓
必要时显示：
“认知探索”
 ↓
打开详细分析页
```

Popup 只展示：

- 推荐结果；
- 一句话摘要；
- 简短理由；
- 可选“认知探索”标记；
- “打开详细页”。

不要把完整 Content Map 和 Reading Plan 塞进扩展 Popup。

详细分析放在 Web 页面。

### 手动提交的特殊原则

PageSift 的“AI 分析”是用户主动行为，因此：

```text
manual_capture = true
```

应被视为强意图信号。

即使模型判断：

```text
relevance = low
```

系统也不能：

- 静默删除；
- 自动隐藏到用户找不到的位置；
- 因为“不符合画像”而拒绝进一步分析。

AI 可以建议：

```text
可以忽略
```

但最终决定仍然属于用户。

# 18. Web 端 V0.1


只需要四个页面。

## 18.1 Inbox

基础分类：

```text
全部
推荐精读
摘要即可
可以忽略
```

另外增加一种**非互斥标记**：

```text
认知探索
```

它不是新的状态，而是可以叠加在任意阅读建议上。例如：

```text
选择性阅读 · 认知探索
```

每张卡显示：

- 标题；
- 来源；
- 一句话摘要；
- 推荐状态；
- 可选探索标记；
- 预计完整阅读时间；
- 推荐实际投入时间；
- 查看分析。

第一版没有 RSS 自动推荐，因此“探索”主要用于帮助用户识别：

> 这篇虽然不是当前画像最相关的内容，但可能值得拓展认知。

等未来加入自动内容流后，再考虑探索内容配额。

## 18.2 内容详情

展示：

1. AI 阅读建议；
2. 一句话总结；
3. 核心观点；
4. 新增信息；
5. 已知/重复信息；
6. Content Map；
7. Reading Plan；
8. 对于观点型内容：反方观点 / 限制条件 / 未解决问题；
9. 可选探索价值说明；
10. 原文入口；
11. 反馈按钮。

## 18.3 阅读偏好

只设置：

- 关注主题；
- 已有基础；
- 不想看的内容；
- 当前阅读目标。

另外明确提示：

> 阅读偏好用于辅助判断，不代表系统只展示这些主题。

未来可以增加：

```text
探索强度：低 / 标准 / 高
```

但 V0.1 不需要开放复杂参数。

## 18.4 简单统计

只统计：

- 总分析数量；
- 推荐精读数量；
- 摘要即可数量；
- 忽略数量；
- 推荐准确率；
- 预计节省阅读时间；
- `低相关但被保留的高探索价值内容` 数量；
- 错杀反馈数量。

# 19. V0.1 后端架构

建议：

```text
Vue 3
   ↓
FastAPI
   ↓
SQLite
   ↓
LLM Provider
```

第一版不需要：

- Kubernetes；
- Redis；
- Kafka；
- 向量数据库；
- Elasticsearch；
- LangGraph；
- Agent Framework。

分析任务状态只需要：

```text
pending
running
completed
failed
```

如果模型调用耗时较长，可以先用一个简单异步 worker / 数据库任务轮询，不需要立即引入复杂任务基础设施。

---

# 20. 数据模型


## 20.1 contents

```text
id
source_type
source_url
canonical_url
capture_mode          # manual / automatic
title
author
markdown
content_type
capture_quality
capture_payload_json
created_at
updated_at
```

## 20.2 analyses

```text
id
content_id
status
triage_json
content_analysis_json
personal_evaluation_json
model
prompt_version
created_at
completed_at
```

`triage_json` 至少预留：

```text
relevance
intrinsic_signal
novelty_signal
exploration_value
discovery_type
decision
reason
```

`personal_evaluation_json` 至少预留：

```text
knowledge_overlap
novel_information
exploration_value
perspective_diversity
recommendation
reading_plan
```

## 20.3 user_profile

```text
id
profile_json
updated_at
```

`profile_json` 内部区分：

```text
interests
knowledge_items
avoid
goal
```

不要把“兴趣”与“已掌握知识”混为同一字段。

## 20.4 feedback

```text
id
content_id
analysis_id
ai_recommendation
recommendation_accuracy
final_action
topic_preference_signal
created_at
```

其中：

```text
topic_preference_signal
```

默认允许为空。只有用户明确表达“多看 / 少看这个主题”时才写入。

# 21. API 第一版

```text
POST /api/contents/analyze
GET  /api/contents
GET  /api/contents/{id}
POST /api/contents/{id}/reanalyze
POST /api/contents/{id}/feedback
GET  /api/profile
PUT  /api/profile
```

`POST /api/contents/analyze` 接收 PageSift 已有结构：

```json
{
  "metadata": {},
  "markdown": "...",
  "contentType": "technical-article",
  "quality": {},
  "extraction": {}
}
```

后端统一转换为内部 `UnifiedContent`。

---

# 22. 长文章处理

不要简单截断。

优先：

```text
完整文章在模型上下文范围内
            ↓
          直接分析
```

超过上下文或达到配置阈值：

```text
Markdown Heading
      ↓
按章节拆分
      ↓
Section Analysis
      ↓
整篇聚合
```

单章节仍过长时再按段落拆分。

原则：

> **允许分块，但不因为长文章直接丢弃后半部分。**

---

# 23. 模型策略

第一版不需要模型路由系统。

建议只支持：

```text
OpenAI-compatible API
```

配置：

```text
base_url
api_key
model
```

后续再考虑：

- 小模型做 Triage；
- 大模型做深度分析；
- 本地模型隐私模式；
- 不同内容类型自动选模型。

这种思路可以借鉴 Summarize 和 AI Video Transcriber 的 BYOM / 多 Provider 设计，但 V0.1 不实现复杂 Provider 管理。

---

# 24. 不要直接复制哪些开源项目能力

## 不做 Karakeep Clone

不重新做：

```text
复杂 bookmark manager
```

## 不做 Summarize Clone

不把：

```text
支持最多输入格式
```

当作 V0.1 目标。

## 不做 Trove AI Clone

不进入：

```text
RAG / 知识图谱 / 第二大脑
```

## 不做 Readability Reader Clone

不开发：

```text
TTS + 完整 Reader
```

## 不做 Papr Clone

第一版不加入：

```text
RSS Feed Manager
```

我们只需要把它们证明有效的部分，放到自己的产品链条上。

---

# 25. 真正应该形成差异化的能力


整个项目真正应该花时间打磨五件事。

## 25.1 Novel Information

不是：

```text
文章讲了什么？
```

而是：

```text
相对于我已经知道的内容，它新增了什么？
```

## 25.2 Selective Reading

不是：

```text
读 / 不读
```

而是：

```text
哪一部分读？
```

## 25.3 Explainable Recommendation

不是：

```text
推荐指数 87
```

而是：

```text
为什么推荐？
为什么跳过？
为什么这篇虽然不相关，却仍值得探索？
```

## 25.4 Feedback Calibration

不是假设 AI 永远正确，而是：

```text
AI 推荐
 ↓
用户实际反馈
 ↓
逐渐校准
```

同时避免把“推荐准确”误解成“用户更喜欢这个主题”。

## 25.5 Cognitive Diversity

这是 V0.3 新增的核心能力。

系统不仅要识别：

```text
和我有关的高价值内容
```

还要识别：

```text
和我当前画像关系不大
但可能拓展认知边界的高价值内容
```

并且在观点型内容中尽量保留：

- 反方观点；
- 限制条件；
- 不确定性；
- 未解决问题。

最终目标不是：

```text
越来越懂我
→ 越来越只给我喜欢的东西
```

而是：

```text
越来越懂我
→ 更准确地过滤噪音
→ 同时保留意外、新观点和跨领域价值
```

# 26. V0.1 开发范围


必须完成：

- PageSift “AI 分析”入口；
- UnifiedContent Web 类型；
- TriageContent；
- AnalyzeContent；
- EvaluateForUser；
- Content Map；
- Novel Information；
- Reading Plan；
- `exploration_value` / `discovery_type`；
- 观点型内容的 counterarguments / limitations 提取；
- Web Inbox；
- 详情页；
- 简单用户画像；
- 推荐反馈；
- SQLite 持久化。

明确不做：

- PDF；
- YouTube；
- Bilibili；
- Podcast；
- RSS；
- RAG；
- 向量数据库；
- 知识图谱；
- 自动画像学习；
- 自动兴趣权重强化；
- 多用户；
- 移动端原生 App；
- TTS；
- 自动推送；
- PageWatch；
- 复杂推荐算法。

V0.1 只把“防茧房所需的数据和判断字段”打好基础，不实现复杂的推荐 Feed。

# 27. 推荐开发顺序


## 阶段 0：不要写页面，先验证 AI 判断

准备约 25～40 篇自己真实会遇到的文章。

除了原来的测试类型：

- 真正高质量；
- 标题党；
- 基础重复；
- 长技术文章；
- 新闻；
- 观点文章；
- 实践教程；
- 自己已经熟悉的主题；
- 自己不熟悉但很重要的主题；

V0.3 额外加入：

- **与你当前兴趣低相关但客观质量很高的文章**；
- **与你既有观点相反的高质量文章**；
- **同一主题下你已知 80%，但仍有 20% 新知识的文章**；
- **包含明确反方观点和限制条件的论证型文章**；
- **跨领域但能提供方法论启发的文章**。

只实现：

```text
Markdown
 ↓
TriageContent
 ↓
AnalyzeContent
 ↓
EvaluateForUser
 ↓
JSON
```

人工验证：

1. 低相关高价值内容是否被保留；
2. AI 是否把“主题熟悉”错误等同于“内容已知”；
3. 摘要是否压掉原文中的反方观点；
4. 用户画像是否过度影响文章自身质量判断。

## 阶段 1：Analysis API

实现：

- FastAPI；
- SQLite；
- 数据模型；
- Prompt version；
- 分析任务状态；
- 记录 `capture_mode`、`discovery_type` 和探索字段。

## 阶段 2：PageSift 接入

增加：

```text
✨ AI 分析
```

并确保手动提交内容不会因低相关性被后台丢弃。

## 阶段 3：Web UI

实现：

- Inbox；
- Detail；
- Preferences；
- Feedback；
- “认知探索”标记。

## 阶段 4：真实使用 2～4 周

不要继续堆功能。

只观察：

- AI 是否真的减少低价值阅读；
- 哪类文章容易误判；
- Novel Information 是否有用；
- 选择性阅读是否比完整摘要更有价值；
- 是否出现“只推荐已有兴趣”的收窄趋势；
- “认知探索”内容是否真的有价值而不是随机噪音。

# 28. V0.1 验收标准


不是：

```text
AI 摘要读起来很好
```

而是以下指标。

## 28.1 推荐准确度

例如：

```text
推荐精读 → 用户认可 ≥ 80%
建议忽略 → 用户认可 ≥ 85%
```

第一版不用把数字当硬 KPI，但要能统计。

## 28.2 阅读时间节省

记录：

```text
完整预计阅读时间
-
实际推荐阅读时间
=
预计节省时间
```

## 28.3 错杀率

重点检查：

> AI 建议忽略，但用户后来发现其实非常有价值。

相比“多推荐一篇普通文章”，错杀真正高价值内容的危害更大。

因此 Triage 应偏保守：

```text
不确定 → continue
```

而不是：

```text
不确定 → ignore
```

## 28.4 章节级建议有效性

检查：

- 推荐跳过的内容是否确实已知/低价值；
- 推荐精读的章节是否真的集中高价值内容。

## 28.5 认知多样性保留率

构造一组：

```text
低画像相关性
+
高内容质量 / 高探索价值
```

的测试文章。

检查系统是否因为：

```text
relevance = low
```

就直接把它们全部压到 `ignore`。

目标不是强制推荐所有跨领域内容，而是：

> **高探索价值内容能够进入人工可见的分析结果，而不是被兴趣模型静默消失。**

## 28.6 观点保真度

对观点型文章检查：

- 原文存在的反方观点是否被保留；
- 文章明确提出的限制条件是否被保留；
- 作者立场与事实陈述是否被混淆；
- 未经验证的数据是否被 AI 当成确定事实。

## 28.7 反馈自强化审计

连续使用一段时间后检查：

```text
某主题的“推荐准确”反馈
```

是否导致：

```text
该主题在内容流中的占比持续异常升高
```

V0.1 不做自动推荐 Feed，但数据模型和反馈逻辑必须保证未来不会天然形成这种强化回路。

# 29. 后续版本路线


> 以下版本号指**产品迭代版本**，不是本文档版本 V0.3。

## 产品 V0.2：内容 Inbox 成熟

增加：

- 批量分析；
- 更好的历史筛选；
- 阅读状态；
- 更多反馈；
- Prompt / 模型效果对比；
- 探索价值筛选与人工验证。

## 产品 V0.3：RSS / 自动内容流

借鉴 Papr / Newscrux：

```text
关注来源
 ↓
自动抓取
 ↓
AI 自动 Triage
 ↓
核心内容 + 探索内容
 ↓
每天只看值得看的
```

此阶段正式加入**探索配额 / 多样性约束**。

可以从一个非常简单的策略开始，例如：

```text
60%～80%：当前核心关注
10%～20%：邻近领域
10%～20%：高价值认知探索
```

具体比例必须由真实使用数据调整，不做死规则。

重点是：

> 自动内容流不能只最大化“个人相关性”。

## 产品 V0.4：音视频

借鉴 Summarize / AI Video Transcriber：

```text
YouTube
Bilibili
Podcast
Audio
Video
 ↓
Transcript
 ↓
Content Map
 ↓
推荐时间段
```

## 产品 V0.5：PDF

借鉴 Readability Reader：

- PDF.js；
- 标题层级；
- 表格/图片结构；
- 长文档章节分析。

## 产品 V1.0：个人信息消费中心

最终形成：

```text
互联网内容
     ↓
统一采集
     ↓
AI 阅读分诊
     ↓
相关高价值 + 认知探索
     ↓
只消费真正有价值的部分
     ↓
真正重要的内容
     ↓
Memento
```

# 30. 开源项目借鉴优先级

如果后续需要真正读源码，推荐顺序：

## 第一优先：Newscrux

研究：

- relevance filter；
- 分析 pipeline；
- structured summary。

目的：优化本项目核心分诊逻辑。

## 第二优先：Summarize

研究：

- Unified Input；
- transcript-first；
- media adapters；
- Side Panel 和后端/本地服务关系。

目的：为未来多模态输入预留正确架构。

## 第三优先：Karakeep

研究：

- Inbox；
- bookmark/content 状态；
- Reader UI；
- RSS；
- self-host UX。

目的：借鉴成熟产品交互，不复制知识库范围。

## 第四优先：Readability Reader

研究：

- PDF；
- YouTube Transcript；
- 本地处理；
- 阅读器体验。

## 第五优先：AI Video Transcriber

研究：

- B站 / YouTube / Podcast 下载；
- FFmpeg；
- ASR；
- 视频处理 pipeline。

## 观察：Papr / Trove AI / Recally

重点观察它们未来在：

- Agent triage；
- 中文互联网采集；
- 内容生命周期；
- 知识库与阅读之间边界

方面如何发展。

---

# 31. 最终产品定义


V0.3 后，产品定义建议正式调整为：

> **AI 内容筛选与消费助手：让 AI 先替用户完成第一轮阅读，识别低价值、重复和真正新增的信息，为值得关注的内容生成章节级阅读计划，同时保留跨领域高价值内容、反方观点和认知探索空间。**

一句更短的产品描述：

> **不是替你读完互联网，而是帮你决定哪里值得亲自读。**

再增加一句产品原则：

> **减少信息噪音，但不减少认知边界。**

技术定位：

```text
PageSift = Web Capture Layer
AI 阅读中心 = Reading Triage + Cognitive Diversity Layer
Memento = Long-term Knowledge Layer
```

这三个组件各自职责明确，未来也可以独立演化。

# 32. 参考项目

检索日期：2026-08-11。

- [alicankiraz1/newscrux](https://github.com/alicankiraz1/newscrux)
- [steipete/summarize](https://github.com/steipete/summarize)
- [karakeep-app/karakeep](https://github.com/karakeep-app/karakeep)
- [ldenoue/readability-read-aloud-web-pdf-ai-summary](https://github.com/ldenoue/readability-read-aloud-web-pdf-ai-summary)
- [l0ng-ai/papr](https://github.com/l0ng-ai/papr)
- [wendy7756/AI-Video-Transcriber](https://github.com/wendy7756/AI-Video-Transcriber)
- [weaiw/trove-ai](https://github.com/weaiw/trove-ai)
- [recally-io/recally](https://github.com/recally-io/recally)

---

# 33. 下一步


下一步仍然不建议继续扩产品功能。

建议直接进入：

```text
TriageContent Prompt
AnalyzeContent Prompt
EvaluateForUser Prompt
JSON Schema
测试文章集
```

但 V0.3 的测试集必须刻意包含：

```text
核心相关内容
低价值噪音
已知重复内容
低相关高价值内容
反方观点内容
跨领域探索内容
```

先证明两个问题同时成立：

1. **AI 能否有效降低无效阅读；**
2. **AI 是否没有因为个人画像而系统性屏蔽高价值的陌生内容。**

如果这两个问题都成立，Web UI、RSS、音视频才值得继续工程扩展。

# 34. GitHub 调研来源与可复用结论

> 调研日期：2026-08-11。以下链接用于后续真正阅读源码时定位，不代表建议直接复制其代码。使用代码前应单独检查对应仓库许可证。

## 34.1 Newscrux

- 仓库：https://github.com/alicankiraz1/newscrux
- 已验证能力：RSS 聚合、AI relevance filter、必要时获取全文、结构化摘要、推送。
- 对本项目最重要的结论：**先筛选，再投入更昂贵的分析**是可行的产品与工程路径。
- 建议重点阅读：relevance filter、pipeline 编排、结构化输出。

## 34.2 Summarize

- 仓库：https://github.com/steipete/summarize
- 已验证能力：Web、PDF、文件、YouTube、Podcast、音频、视频等统一输入；媒体优先使用已有 transcript，缺失时再转录；支持浏览器侧入口。
- 对本项目最重要的结论：未来应该围绕 `UnifiedContent` 设计，而不是围绕 `Article` 设计。
- 建议重点阅读：媒体 Adapter、transcript-first、统一输入协议、浏览器 Side Panel 与本地服务关系。

## 34.3 Karakeep

- 仓库：https://github.com/karakeep-app/karakeep
- 许可证：AGPL-3.0。
- 已验证能力：链接/图片/PDF 收藏、全文与语义搜索、LLM 标签和摘要、浏览器扩展、移动端、离线阅读、RSS、Highlight、全页归档、视频归档、REST API、自托管。
- 对本项目最重要的结论：Inbox、阅读状态和内容生命周期已经有成熟范式，不需要重新发明。
- 建议重点研究产品交互与状态模型，不建议直接复制代码。

## 34.4 Readability Reader

- 仓库：https://github.com/ldenoue/readability-read-aloud-web-pdf-ai-summary
- 已验证能力：Manifest V3、Mozilla Readability、Defuddle 站点提取、YouTube captions/chapters、PDF.js、本地摘要、TTS、本地阅读历史与搜索。
- 对本项目最重要的结论：PageSift 当前的 `Readability + Defuddle + 站点适配` 技术方向合理；PDF、YouTube、本地模式以后有清晰参考实现。

## 34.5 Papr

- 仓库：https://github.com/l0ng-ai/papr
- 已验证能力：本地优先 RSS Reader，与 Agent CLI 共用本地数据库，Agent 可读取、搜索、分诊订阅内容。
- 对本项目最重要的结论：RSS 最适合作为后续自动内容流，而不是 V0.1 的入口。

## 34.6 AI Video Transcriber

- 仓库：https://github.com/wendy7756/AI-Video-Transcriber
- 许可证：Apache-2.0。
- 已验证能力：YouTube、Bilibili、TikTok、Apple Podcasts、SoundCloud 等多平台；本地音视频；字幕优先、Faster-Whisper 回退；FFmpeg；OpenAI-compatible 模型。
- 对本项目最重要的结论：音视频输入层无需从零设计，应采用 `Subtitle/Transcript First → ASR Fallback → Topic Segmentation`。

## 34.7 Trove AI

- 仓库：https://github.com/weaiw/trove-ai
- 已验证能力：中文互联网多平台采集、Web/文件知识库、RAG、知识图谱、学习路径、Obsidian 同步、MCP、移动适配。
- 对本项目最重要的结论：它证明“采集后继续做连接、比较、复用”有价值，同时也说明产品很容易膨胀成完整知识管理系统。
- 对我们的约束：AI 阅读中心停在“分诊与消费”，长期沉淀继续交给 Memento。

## 34.8 Recally

- 仓库：https://github.com/recally-io/recally
- 已验证能力：网页采集、Markdown 转换、AI 摘要、标签、分类、全文搜索、自托管；视频/PDF/Podcast 等部分能力仍在路线图中。
- 对本项目最重要的结论：`Capture → Organize → Rediscover` 已有成熟产品路径，我们不应把这些能力当作核心创新点。

---


# 35. 防信息茧房与认知多样性机制

V0.3 把信息茧房视为产品架构问题，而不是一个额外提示。

## 35.1 不把“相关性”当作“价值”

禁止使用：

```text
relevance 低
→ 自动低价值
→ 自动忽略
```

必须至少同时考虑：

```text
内容自身质量
新增信息
探索价值
观点多样性
用户当前相关性
```

其中用户相关性只是一个维度。

## 35.2 手动输入不静默过滤

PageSift 的手动提交表示：

```text
用户已经主动注意到这篇内容
```

因此 AI 的职责是：

```text
建议如何分配注意力
```

而不是：

```text
替用户决定这篇东西不该存在
```

所有手动提交都必须可回看、可强制完整分析。

## 35.3 探索属性与阅读动作分离

不要增加一个模糊的：

```text
recommendation = explore
```

而是：

```json
{
  "recommendation": "selective_read",
  "discovery_type": "outside_profile_high_value",
  "exploration_value": "high"
}
```

这样“是否值得读”与“为什么值得突破画像去读”可以同时表达。

## 35.4 摘要必须保留原文中的真实分歧

对于存在争议或论证结构的内容，允许原文只有一方观点，也允许存在多方观点。

系统不能为了“平衡”凭空制造反方观点，但如果原文确实包含：

- 反对意见；
- 限制条件；
- 不确定性；
- 作者承认的缺陷；
- 未验证数据；

AI 不应在总结时把它们消失掉。

## 35.5 已知知识按知识点判断，不按主题封锁

错误：

```text
用户懂 Git
→ Git 内容都重复
```

正确：

```text
用户已知 Git rebase 基础
+
本文包含 --onto 的复杂迁移案例
→ 部分已知 + 存在新增信息
```

因此 `knowledge_items` 比单纯的 topic level 更适合长期演进。

## 35.6 反馈默认只校准判断，不强化兴趣

默认：

```text
👍 判断准确
```

含义是：

```text
这次 AI 判断正确
```

而不是：

```text
以后多给我这个主题
```

只有用户明确表达兴趣变化时才修改兴趣画像。

## 35.7 自动内容流必须保留探索预算

V0.1 是手动输入，不需要做复杂推荐 Feed。

未来加入 RSS / 自动订阅后，内容流应同时包含：

```text
核心相关
邻近领域
认知探索
```

而不是全部按照个人相关性排序。

探索比例应作为可调参数，并通过真实反馈验证。

## 35.8 可解释性优先于隐藏

系统必须尽量说明：

```text
为什么建议忽略？
为什么认为已知？
为什么认为值得精读？
为什么这篇低相关内容仍值得探索？
```

用户应该可以看到被忽略的内容，并推翻 AI 的判断。

---

## 35.9 V0.3 推荐结构化字段

建议在最终 JSON Schema 中预留：

```json
{
  "triage": {
    "relevance": "low",
    "intrinsic_signal": "high",
    "novelty_signal": "high",
    "exploration_value": "high",
    "discovery_type": "outside_profile_high_value",
    "decision": "continue",
    "reason": "..."
  },
  "content_analysis": {
    "one_sentence_summary": "...",
    "key_points": [],
    "counterarguments": [],
    "limitations": [],
    "unresolved_questions": [],
    "unverified_claims": []
  },
  "personal_evaluation": {
    "knowledge_overlap": "low",
    "novel_information": [],
    "perspective_diversity": "high",
    "exploration_value": "high",
    "recommendation": "selective_read",
    "why_outside_profile": "...",
    "reading_plan": []
  }
}
```

这套字段不要求 V0.1 UI 全部展示，但后端和 Prompt 设计应该从一开始保留正确方向。


# 36. 开发时的最终原则


后续每出现一个新功能想法，都先问四个问题：

1. **它是在提升“阅读分诊准确度”，还是只是在增加功能数量？**
2. **它是否已有成熟开源项目可以承担或提供参考？**
3. **它应该属于 PageSift、AI 阅读中心，还是 Memento？**
4. **它会不会因为提升个性化，而缩窄用户的认知边界？**

只有明确提升下面五个能力的功能，才优先进入 AI 阅读中心：

```text
Novel Information
Selective Reading
Explainable Recommendation
Feedback Calibration
Cognitive Diversity
```

V0.3 再增加六条实现原则：

```text
低相关 ≠ 低价值
手动输入不静默过滤
不确定 → continue
反馈准确 ≠ 兴趣强化
保留原文真实分歧
探索内容必须可解释
```

因此，V0.1 的成功标准不是“支持多少内容类型”，而是：

> **AI 是否真的帮用户少看了大量低价值内容，同时没有错过真正重要的信息，也没有把用户越来越封闭在已有兴趣和认知里。**

