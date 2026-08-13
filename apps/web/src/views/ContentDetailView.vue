<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import {
  getContent,
  getProfile,
  retryAnalysis,
  saveFeedback,
  type FeedbackUpdate,
  type Recommendation,
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
const profile = useQuery({ queryKey: ['profile'], queryFn: getProfile })
const content = useQuery({
  queryKey: ['content', contentId],
  queryFn: () => getContent(contentId),
  refetchInterval: (query) => {
    const status = query.state.data?.analysis_status
    return status === 'pending' || status === 'running' ? 5000 : false
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
const renderedMarkdown = computed(() => {
  const data = content.data.value
  return data ? renderMarkdown(data.markdown, data.source_url) : ''
})
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

      <div v-if="content.data.value.analysis_status === 'pending'" class="pending-notice">
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
          v-if="content.data.value.personal_evaluation?.reading_plan.length"
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
          <button class="view-toggle" type="button" @click="showMarkdownSource = !showMarkdownSource">
            {{ showMarkdownSource ? '阅读模式' : '查看源码' }}
          </button>
        </div>
        <pre v-if="showMarkdownSource" class="markdown-source">{{ content.data.value.markdown }}</pre>
        <div v-else class="markdown-body" v-html="renderedMarkdown"></div>
      </article>
    </template>
  </section>
</template>
