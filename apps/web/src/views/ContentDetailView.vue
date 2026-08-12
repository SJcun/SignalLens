<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import { getContent, retryAnalysis } from '../api'
import { renderMarkdown } from '../markdown'

const recommendationText = {
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
