<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import {
  getContent,
  getProfile,
  retryAnalysis,
  runAnalysisNow,
  saveFeedback,
  translateContent,
  type FeedbackUpdate,
  type Recommendation,
  type SectionRef,
} from '../api'
import { renderMarkdown } from '../markdown'

const recommendationText: Record<Recommendation, string> = {
  ignore: '可以忽略',
  summary_enough: '摘要即可',
  selective_read: '选择性阅读',
  deep_read: '全文精读',
}

const readingActionText = {
  skip: '跳过',
  skim: '浏览',
  read: '阅读',
  deep_read: '精读',
}

const statusText = {
  pending: '等待分析',
  running: '分析中',
  completed: '分析完成',
  failed: '分析失败',
}

const route = useRoute()
const contentId = String(route.params.contentId)
const queryClient = useQueryClient()
const showMarkdownSource = ref(false)
const showTranslation = ref(false)
// 顺序式引导阅读流：true 为引导阅读，false 为完整原文；切换不修改任何 AI 结果。
const guidedMode = ref(true)
// 本次页面会话中手动展开的折叠章节引用，模式切换后仍然保留。
const expandedSections = reactive(new Set<string>())
const profile = useQuery({ queryKey: ['profile'], queryFn: getProfile })
const content = useQuery({
  queryKey: ['content', contentId],
  queryFn: () => getContent(contentId),
  refetchInterval: (query) => {
    const status = query.state.data?.analysis_status
    const translationStatus = query.state.data?.translation?.status
    return status === 'pending' || status === 'running'
      || translationStatus === 'pending' || translationStatus === 'running'
      ? 5000
      : false
  },
})
const retry = useMutation({
  mutationFn: () => retryAnalysis(content.data.value!.analysis_id),
  onSuccess: async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['content', contentId] }),
      queryClient.invalidateQueries({ queryKey: ['contents'] }),
    ])
  },
})
const runNow = useMutation({
  mutationFn: () => runAnalysisNow(content.data.value!.analysis_id),
  onSuccess: async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['content', contentId] }),
      queryClient.invalidateQueries({ queryKey: ['contents'] }),
    ])
  },
})

/** 将后端 UTC 时间固定按北京时间展示。 */
function formatScheduleTime(value: string | null): string {
  if (!value) return '下一个设定时段'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function requestRunNow(): void {
  if (!window.confirm('立即整理会绕过低价时段限制，可能产生更高费用。继续吗？')) return
  runNow.mutate()
}
const renderedMarkdown = computed(() => {
  const data = content.data.value
  return data ? renderMarkdown(data.markdown, data.source_url) : ''
})

interface GuidedSection {
  section_ref: string
  title: string
  action: 'skip' | 'skim' | 'read' | 'deep_read'
  reason: string
  summary: string
  /** 章节正文渲染后的 HTML，按来源行号在原位置展示。 */
  markdown: string
}

/** 中英对照视图的一个章节：左右两侧共用动作徽章，正文分别取原文与译文。 */
interface ComparisonSection {
  section_ref: string
  title: string
  translatedTitle: string
  action: 'skip' | 'skim' | 'read' | 'deep_read'
  /** 左侧原文渲染后的 HTML。 */
  markdown: string
  /** 右侧译文渲染后的 HTML；译文不可用时为空字符串。 */
  translatedMarkdown: string
}

const guidedFlowEnabled = computed(() => content.data.value?.guided_flow_available === true)

/** 译文完整且块带行号时，对照视图可以按章节行号切分译文并标注。 */
const guidedTranslationReady = computed(() => {
  const translation = content.data.value?.translation
  if (!translation || translation.status !== 'completed' || !translation.blocks.length) return false
  return translation.blocks.every(
    (block) => block.start_line != null && block.end_line != null,
  )
})

/** 行号范围内按来源顺序拼接译文块；无译文的共享块（代码、图片）原样保留。 */
function translatedMarkdownFor(startLine: number, endLine: number): string {
  const blocks = content.data.value?.translation?.blocks ?? []
  return blocks
    .filter(
      (block) =>
        block.start_line != null && block.start_line >= startLine && block.start_line < endLine,
    )
    .map((block) => block.translated_markdown || block.source_markdown)
    .join('\n\n')
}

/** 从译文标题行提取纯文本，与章节清单标题的展示口径一致。 */
function plainHeadingText(heading: string): string {
  return heading.replace(/^#{1,6}\s+/, '').replace(/[ \t]+#+[ \t]*$/, '').trim()
}

/** 返回章节标题行的译文纯文本；译文不可用时回退到原文标题。 */
function translatedSectionTitle(section: SectionRef): string {
  const blocks = content.data.value?.translation?.blocks ?? []
  const headingBlock = blocks.find(
    (block) =>
      block.kind === 'heading' &&
      block.start_line != null &&
      block.end_line != null &&
      block.start_line <= section.start_line &&
      section.start_line < block.end_line,
  )
  return headingBlock?.translated_markdown
    ? plainHeadingText(headingBlock.translated_markdown)
    : section.title
}

/** 按系统章节清单的原始顺序组合每个主章节的动作、原因、摘要与原文。 */
const guidedSections = computed<GuidedSection[]>(() => {
  const data = content.data.value
  if (!data?.section_index || !data.personal_evaluation || !data.content_analysis) return []
  const planByRef = new Map(
    data.personal_evaluation.reading_plan
      .filter((item) => item.section_ref)
      .map((item) => [item.section_ref, item]),
  )
  const summaryByRef = new Map(
    data.content_analysis.content_map
      .filter((item) => item.section_ref)
      .map((item) => [item.section_ref, item]),
  )
  const lines = data.markdown.split('\n')
  return data.section_index.sections.map((section) => {
    const plan = planByRef.get(section.section_ref)
    const mapItem = summaryByRef.get(section.section_ref)
    return {
      section_ref: section.section_ref,
      title: section.title,
      action: plan?.action ?? 'read',
      reason: plan?.reason ?? '',
      summary: mapItem?.summary ?? '',
      markdown: renderMarkdown(
        lines.slice(section.start_line + 1, section.end_line).join('\n'),
        data.source_url,
      ),
    }
  })
})

/** 文章标题、导语和主章节之外的上下文块始终完整展示。 */
const guidedContext = computed(() => {
  const data = content.data.value
  const firstSection = data?.section_index?.sections[0]
  if (!data || !firstSection) return ''
  const lines = data.markdown.split('\n')
  return renderMarkdown(lines.slice(0, firstSection.start_line).join('\n'), data.source_url)
})

/** 对照视图能否按章节标注：引导流可用且译文块带行号。 */
const comparisonAnnotated = computed(() => guidedFlowEnabled.value && guidedTranslationReady.value)

/** 中英对照视图按章节组织左右两侧：左侧原文、右侧译文，共用动作徽章。 */
const comparisonSections = computed<ComparisonSection[]>(() => {
  const data = content.data.value
  if (!data?.section_index || !data.personal_evaluation) return []
  const planByRef = new Map(
    data.personal_evaluation.reading_plan
      .filter((item) => item.section_ref)
      .map((item) => [item.section_ref, item]),
  )
  const lines = data.markdown.split('\n')
  const translated = guidedTranslationReady.value
  return data.section_index.sections.map((section) => ({
    section_ref: section.section_ref,
    title: section.title,
    translatedTitle: translated ? translatedSectionTitle(section) : section.title,
    action: planByRef.get(section.section_ref)?.action ?? 'read',
    markdown: renderMarkdown(
      lines.slice(section.start_line + 1, section.end_line).join('\n'),
      data.source_url,
    ),
    translatedMarkdown: translated
      ? renderMarkdown(
          translatedMarkdownFor(section.start_line + 1, section.end_line),
          data.source_url,
        )
      : '',
  }))
})

/** 对照视图右侧：第一个主章节之前的译文上下文（标题与导语）。 */
const comparisonContextTranslated = computed(() => {
  const data = content.data.value
  const firstSection = data?.section_index?.sections[0]
  if (!data || !firstSection || !guidedTranslationReady.value) return ''
  return renderMarkdown(translatedMarkdownFor(0, firstSection.start_line), data.source_url)
})

/** 顶部总览只说明 AI 如何分配章节动作，不承担目录导航职责。 */
const guidedActionCounts = computed(() => {
  const counts = { skip: 0, skim: 0, read: 0, deep_read: 0 }
  for (const section of guidedSections.value) counts[section.action]++
  return counts
})

function toggleSection(sectionRef: string): void {
  if (expandedSections.has(sectionRef)) expandedSections.delete(sectionRef)
  else expandedSections.add(sectionRef)
}
const canTranslate = computed(() => {
  const language = content.data.value?.source_language.toLowerCase()
  return Boolean(language?.startsWith('en'))
})
const translation = useMutation({
  mutationFn: () => translateContent(contentId),
  onSuccess: async () => {
    await queryClient.invalidateQueries({ queryKey: ['content', contentId] })
  },
})
const renderedTranslatedMarkdown = computed(() => {
  const data = content.data.value
  if (!data?.translation) return ''
  // 译文按原块顺序重新组成一篇完整 Markdown；代码、图片等共享块原样保留。
  const translatedMarkdown = data.translation.blocks
    .map((block) => block.translated_markdown || block.source_markdown)
    .join('\n\n')
  return renderMarkdown(translatedMarkdown, data.source_url)
})
const translationButtonText = computed(() => {
  if (translation.isPending.value) return '正在创建任务…'
  const task = content.data.value?.translation
  if (!task) return '翻译为中文'
  if (task.status === 'pending') return '等待翻译…'
  if (task.status === 'running') {
    return `翻译中 ${task.completed_blocks}/${task.total_blocks}`
  }
  if (task.status === 'failed') return '重试翻译'
  return showTranslation.value ? '只看原文' : '中英对照'
})

watch(
  () => content.data.value?.translation?.status,
  (status) => {
    // 选择性阅读文章翻译完成后留在原文引导流，不打断阅读；
    // 引导流不可用时才自动切到双文档对照视图。
    if (status === 'completed' && !guidedFlowEnabled.value) showTranslation.value = true
  },
  { immediate: true },
)

/** 已完成时切换阅读视图，其余状态由后端幂等创建或重试任务。 */
function handleTranslation(): void {
  if (content.data.value?.translation?.status === 'completed') {
    showTranslation.value = !showTranslation.value
    showMarkdownSource.value = false
    return
  }
  translation.mutate()
}
const currentRecommendationText = computed(() => {
  const recommendation = content.data.value?.ai_recommendation
  return recommendation && recommendation in recommendationText
    ? recommendationText[recommendation as Recommendation]
    : '暂无建议'
})
type FeedbackForm = Omit<FeedbackUpdate, 'preferred_recommendation'> & {
  preferred_recommendation: Recommendation | ''
}
const feedbackForm = reactive<FeedbackForm>({
  preferred_recommendation: '',
  time_worthwhile: 'yes',
  new_knowledge: 'some',
  summary_quality: 'accurate',
  key_takeaway: '',
})

watch(
  () => content.data.value?.feedback,
  (feedback) => {
    if (!feedback) return
    Object.assign(feedbackForm, {
      preferred_recommendation: feedback.preferred_recommendation || '',
      time_worthwhile: feedback.time_worthwhile,
      new_knowledge: feedback.new_knowledge,
      summary_quality: feedback.summary_quality,
      key_takeaway: feedback.key_takeaway || '',
    })
  },
  { immediate: true },
)

const submitFeedback = useMutation({
  mutationFn: () => {
    const preferredRecommendation = feedbackForm.preferred_recommendation
    if (!preferredRecommendation) throw new Error('请选择你认为最合适的阅读投入')
    return saveFeedback(content.data.value!.analysis_id, {
      ...feedbackForm,
      preferred_recommendation: preferredRecommendation,
    })
  },
  onSuccess: async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['content', contentId] }),
      queryClient.invalidateQueries({ queryKey: ['contents'] }),
      queryClient.invalidateQueries({ queryKey: ['calibration-stats'] }),
    ])
  },
})
</script>

<template>
  <section>
    <p class="eyebrow">Content Analysis</p>
    <h1>{{ content.data.value?.title || '内容分析' }}</h1>

    <div v-if="content.isPending.value" class="panel">
      <h2>正在加载内容…</h2>
    </div>
    <div v-else-if="content.isError.value" class="panel error-panel">
      <h2>内容加载失败</h2>
      <p>{{ content.error.value?.message }}</p>
    </div>
    <template v-else-if="content.data.value">
      <div class="detail-meta">
        <span class="analysis-status" :class="content.data.value.analysis_status">
          {{ statusText[content.data.value.analysis_status] }}
        </span>
        <span>提取质量：{{ content.data.value.capture_quality }}</span>
        <a :href="content.data.value.source_url" target="_blank" rel="noreferrer">打开原文 ↗</a>
      </div>

      <div v-if="content.data.value.queue.waiting_for_schedule" class="pending-notice">
        <span>
          已完成的阶段会安全保留，任务将在
          {{ formatScheduleTime(content.data.value.queue.next_eligible_at) }}继续整理。
        </span>
        <button class="retry-button" :disabled="runNow.isPending.value" @click="requestRunNow">
          {{ runNow.isPending.value ? '正在提交…' : '立即整理' }}
        </button>
        <span v-if="runNow.isError.value">{{ runNow.error.value?.message }}</span>
      </div>
      <div
        v-else-if="content.data.value.analysis_status === 'pending' && content.data.value.queue.execution_mode === 'immediate'"
        class="pending-notice"
      >
        已请求立即整理，正在等待 Worker 领取任务。
      </div>
      <div v-else-if="content.data.value.analysis_status === 'pending'" class="pending-notice">
        正文已经成功导入，正在等待 Worker 领取分析任务。
      </div>
      <div v-else-if="content.data.value.analysis_status === 'running'" class="pending-notice">
        AI 正在分诊和分析这篇内容，页面会自动刷新。
      </div>
      <div v-else-if="content.data.value.analysis_status === 'failed'" class="pending-notice error-panel">
        <span>本次分析失败，原始正文仍已安全保存。</span>
        <button class="retry-button" :disabled="retry.isPending.value" @click="retry.mutate()">
          {{ retry.isPending.value ? '正在重新提交…' : '重新分析' }}
        </button>
        <span v-if="retry.isError.value">{{ retry.error.value?.message }}</span>
      </div>

      <article v-if="content.data.value.personal_evaluation" class="result-hero">
        <p class="eyebrow">阅读建议</p>
        <h2>{{ recommendationText[content.data.value.personal_evaluation.recommendation] }}</h2>
        <p>{{ content.data.value.personal_evaluation.recommendation_reason }}</p>
        <p v-if="content.data.value.personal_evaluation.why_outside_profile" class="explore-callout">
          认知探索：{{ content.data.value.personal_evaluation.why_outside_profile }}
        </p>
      </article>

      <article v-if="content.data.value.content_analysis" class="detail-section result-section">
        <p class="summary-lead">{{ content.data.value.content_analysis.one_sentence_summary }}</p>
        <p>{{ content.data.value.content_analysis.summary }}</p>

        <div v-if="content.data.value.content_analysis.key_points.length" class="result-block">
          <h2>关键要点</h2>
          <ul>
            <li v-for="point in content.data.value.content_analysis.key_points" :key="point">
              {{ point }}
            </li>
          </ul>
        </div>

        <div
          v-if="!guidedFlowEnabled && content.data.value.personal_evaluation?.reading_plan.length"
          class="result-block"
        >
          <h2>阅读计划</h2>
          <div class="reading-plan">
            <div
              v-for="item in content.data.value.personal_evaluation.reading_plan"
              :key="`${item.section}-${item.action}`"
              class="reading-plan-item"
            >
              <span>{{ readingActionText[item.action] }}</span>
              <strong>{{ item.section }}</strong>
              <p>{{ item.reason }}</p>
            </div>
          </div>
        </div>

        <div class="evidence-grid">
          <div v-if="content.data.value.content_analysis.counterarguments.length">
            <h2>原文中的反方观点</h2>
            <ul>
              <li
                v-for="item in content.data.value.content_analysis.counterarguments"
                :key="item"
              >
                {{ item }}
              </li>
            </ul>
          </div>
          <div v-if="content.data.value.content_analysis.limitations.length">
            <h2>限制条件</h2>
            <ul>
              <li v-for="item in content.data.value.content_analysis.limitations" :key="item">
                {{ item }}
              </li>
            </ul>
          </div>
          <div v-if="content.data.value.content_analysis.unverified_claims.length">
            <h2>未验证主张</h2>
            <ul>
              <li
                v-for="item in content.data.value.content_analysis.unverified_claims"
                :key="item"
              >
                {{ item }}
              </li>
            </ul>
          </div>
        </div>
      </article>

      <article v-else-if="content.data.value.triage?.decision === 'ignore'" class="detail-section">
        <h2>快速分诊结论</h2>
        <p>{{ content.data.value.triage.reason }}</p>
      </article>

      <form
        v-if="content.data.value.analysis_status === 'completed'"
        class="detail-section feedback-form"
        @submit.prevent="submitFeedback.mutate()"
      >
        <div class="section-heading">
          <div>
            <p class="eyebrow">Human Calibration</p>
            <h2>{{ profile.data.value?.evaluation_mode ? '阅读后评测' : '反馈 AI 判断' }}</h2>
          </div>
          <span v-if="content.data.value.feedback" class="saved-badge">已评价</span>
        </div>
        <p>
          {{ profile.data.value?.evaluation_mode
            ? '请在完成实际阅读后评价。你的答案会和本次 AI 结果快照一起保存。'
            : '评测模式已关闭，但你仍可以随时修正 AI 的判断。' }}
        </p>

        <div class="feedback-grid">
          <label>
            <span>阅读后，你认为最合适的阅读投入</span>
            <small>AI 当前建议：{{ currentRecommendationText }}</small>
            <select v-model="feedbackForm.preferred_recommendation" required>
              <option value="" disabled>请选择</option>
              <option value="ignore">可以忽略</option>
              <option value="summary_enough">摘要即可</option>
              <option value="selective_read">选择性阅读</option>
              <option value="deep_read">全文精读</option>
            </select>
          </label>
          <label>
            <span>实际是否值得投入时间</span>
            <select v-model="feedbackForm.time_worthwhile">
              <option value="yes">值得</option>
              <option value="partly">部分值得</option>
              <option value="no">不值得</option>
            </select>
          </label>
          <label>
            <span>获得了多少新知识</span>
            <select v-model="feedbackForm.new_knowledge">
              <option value="much">很多</option>
              <option value="some">一些</option>
              <option value="none">没有</option>
            </select>
          </label>
          <label>
            <span>AI 摘要质量</span>
            <select v-model="feedbackForm.summary_quality">
              <option value="accurate">准确</option>
              <option value="omission">有重要遗漏</option>
              <option value="misleading">存在误导</option>
              <option value="not_sure">暂时无法判断</option>
            </select>
          </label>
        </div>

        <label class="feedback-note">
          <span>最重要的收获，或 AI 遗漏了什么（选填）</span>
          <textarea
            v-model="feedbackForm.key_takeaway"
            rows="3"
            maxlength="2000"
            placeholder="一句话就够；早期评测阶段建议填写。"
          ></textarea>
        </label>
        <div class="form-actions">
          <button class="primary-button" type="submit" :disabled="submitFeedback.isPending.value">
            {{ submitFeedback.isPending.value
              ? '正在保存…'
              : content.data.value.feedback ? '更新评价' : '提交评价' }}
          </button>
          <span v-if="submitFeedback.isSuccess.value" class="success-text">评价已保存。</span>
          <span v-if="submitFeedback.isError.value" class="error-text">
            {{ submitFeedback.error.value?.message }}
          </span>
        </div>
      </form>

      <article class="detail-section">
        <div class="section-heading">
          <h2>正文</h2>
          <div class="section-actions">
            <button
              v-if="canTranslate"
              class="view-toggle"
              type="button"
              :disabled="translation.isPending.value
                || content.data.value.translation?.status === 'pending'
                || content.data.value.translation?.status === 'running'"
              @click="handleTranslation"
            >
              {{ translationButtonText }}
            </button>
            <button
              class="view-toggle"
              type="button"
              @click="showMarkdownSource = !showMarkdownSource"
            >
              {{ showMarkdownSource ? '阅读模式' : '查看源码' }}
            </button>
          </div>
        </div>
        <p v-if="translation.isError.value" class="error-text">
          {{ translation.error.value?.message }}
        </p>
        <div
          v-if="content.data.value.translation?.status === 'failed'"
          class="translation-error"
        >
          翻译失败：{{ content.data.value.translation.last_error || '模型未返回有效译文' }}
        </div>
        <pre v-if="showMarkdownSource" class="markdown-source">{{ content.data.value.markdown }}</pre>
        <div
          v-else-if="showTranslation && content.data.value.translation?.status === 'completed'"
          class="translation-comparison"
        >
          <section class="translation-document">
            <h3 class="translation-document-title">原文</h3>
            <template v-if="comparisonAnnotated">
              <div class="guided-context markdown-body" v-html="guidedContext"></div>
              <div
                v-for="section in comparisonSections"
                :key="`source-${section.section_ref}`"
                class="guided-section"
                :class="`guided-action-${section.action}`"
              >
                <div class="guided-section-head">
                  <h4 class="comparison-section-title">{{ section.title }}</h4>
                  <span class="guided-action-badge">
                    {{ readingActionText[section.action] }}
                  </span>
                </div>
                <div class="guided-expanded markdown-body" v-html="section.markdown"></div>
              </div>
            </template>
            <div v-else class="markdown-body" v-html="renderedMarkdown"></div>
          </section>
          <section class="translation-document translated">
            <h3 class="translation-document-title">中文译文</h3>
            <template v-if="comparisonAnnotated">
              <div class="guided-context markdown-body" v-html="comparisonContextTranslated"></div>
              <div
                v-for="section in comparisonSections"
                :key="`translated-${section.section_ref}`"
                class="guided-section"
                :class="`guided-action-${section.action}`"
              >
                <div class="guided-section-head">
                  <h4 class="comparison-section-title">{{ section.translatedTitle }}</h4>
                  <span class="guided-action-badge">
                    {{ readingActionText[section.action] }}
                  </span>
                </div>
                <div class="guided-expanded markdown-body" v-html="section.translatedMarkdown"></div>
              </div>
            </template>
            <div v-else class="markdown-body" v-html="renderedTranslatedMarkdown"></div>
          </section>
        </div>
        <div v-else-if="guidedFlowEnabled" class="guided-flow">
          <div class="guided-overview">
            <span class="guided-mode-badge">{{ guidedMode ? '选择性阅读' : '完整原文' }}</span>
            <span class="guided-counts">
              {{ guidedActionCounts.deep_read }} 节重点精读 · {{ guidedActionCounts.read }} 节建议阅读
              · {{ guidedActionCounts.skim }} 节浏览摘要 · {{ guidedActionCounts.skip }} 节跳过
            </span>
            <button class="view-toggle" type="button" @click="guidedMode = !guidedMode">
              {{ guidedMode ? '完整原文' : '引导阅读' }}
            </button>
          </div>
          <template v-if="guidedMode">
            <div class="guided-context markdown-body" v-html="guidedContext"></div>
            <section
              v-for="section in guidedSections"
              :key="section.section_ref"
              class="guided-section"
              :class="`guided-action-${section.action}`"
            >
              <div class="guided-section-head">
                <h3 class="guided-section-title">{{ section.title }}</h3>
                <span class="guided-action-badge">{{ readingActionText[section.action] }}</span>
              </div>
              <template v-if="section.action === 'skip'">
                <p class="guided-reason">{{ section.reason }}</p>
                <button
                  class="guided-expand"
                  type="button"
                  @click="toggleSection(section.section_ref)"
                >
                  {{ expandedSections.has(section.section_ref) ? '收起原文' : '展开本节原文' }}
                </button>
                <div
                  v-if="expandedSections.has(section.section_ref)"
                  class="guided-expanded markdown-body"
                  v-html="section.markdown"
                ></div>
              </template>
              <template v-else-if="section.action === 'skim'">
                <p class="guided-summary">{{ section.summary }}</p>
                <p class="guided-reason">{{ section.reason }}</p>
                <button
                  class="guided-expand"
                  type="button"
                  @click="toggleSection(section.section_ref)"
                >
                  {{ expandedSections.has(section.section_ref) ? '收起原文' : '展开本节原文' }}
                </button>
                <div
                  v-if="expandedSections.has(section.section_ref)"
                  class="guided-expanded markdown-body"
                  v-html="section.markdown"
                ></div>
              </template>
              <template v-else>
                <p v-if="section.reason" class="guided-reason">{{ section.reason }}</p>
                <div class="guided-expanded markdown-body" v-html="section.markdown"></div>
              </template>
            </section>
          </template>
          <div v-else class="markdown-body" v-html="renderedMarkdown"></div>
        </div>
        <div v-else class="markdown-body" v-html="renderedMarkdown"></div>
      </article>
    </template>
  </section>
</template>
