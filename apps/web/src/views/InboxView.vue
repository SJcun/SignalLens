<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'

import { getContents, getHealth, type ContentSummary, type Recommendation } from '../api'

const recommendationText: Record<Recommendation, string> = {
  ignore: '可以忽略',
  summary_enough: '摘要即可',
  selective_read: '选择性阅读',
  deep_read: '全文精读',
}

const health = useQuery({ queryKey: ['health'], queryFn: getHealth, retry: 1 })
const contents = useQuery({
  queryKey: ['contents'],
  queryFn: getContents,
  refetchInterval: 5000,
})

type Filter = 'all' | 'deep_read' | 'summary_enough' | 'selective_read' | 'ignore' | 'explore'

const activeFilter = ref<Filter>('all')
const filters: Array<{ value: Filter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'deep_read', label: '全文精读' },
  { value: 'summary_enough', label: '摘要即可' },
  { value: 'selective_read', label: '选择性阅读' },
  { value: 'ignore', label: '可以忽略' },
  { value: 'explore', label: '认知探索' },
]

const filteredContents = computed(() => {
  const rows = contents.data.value || []
  if (activeFilter.value === 'all') return rows
  if (activeFilter.value === 'explore') {
    return rows.filter((item) => item.discovery_type === 'outside_profile_high_value')
  }
  return rows.filter((item) => item.recommendation === activeFilter.value)
})

const statusText: Record<ContentSummary['analysis_status'], string> = {
  pending: '等待分析',
  running: '分析中',
  completed: '分析完成',
  failed: '分析失败',
}

/** 在基础分析状态上补充定时等待和用户立即要求。 */
function analysisStatusText(item: ContentSummary): string {
  if (item.queue.waiting_for_schedule) return '等待整理时段'
  if (
    item.queue.execution_mode === 'immediate'
    && (item.analysis_status === 'pending' || item.analysis_status === 'running')
  ) return '立即整理'
  return statusText[item.analysis_status]
}

/** 使用用户本地时区展示采集时间。 */
function formatTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

/** 展示最终分类的来源，避免把用户修正误认为 AI 原始建议。 */
function correctionText(item: ContentSummary): string | null {
  if (!item.user_recommendation) return null
  if (item.user_recommendation === item.ai_recommendation) {
    return `用户确认：${recommendationText[item.user_recommendation]}`
  }
  const aiText = item.ai_recommendation
    ? recommendationText[item.ai_recommendation]
    : '暂无建议'
  return `用户修正：${recommendationText[item.user_recommendation]} · AI 原建议：${aiText}`
}

/** Inbox 只显示简短 Delta 摘要，不堆叠复杂关系图。 */
function deltaSummaryText(
  summary: NonNullable<ContentSummary['delta_summary']>,
): string {
  if (summary.cognitive_gain_count > 0 && summary.known_duplicate_count > 0) {
    return `认知增量 ${summary.cognitive_gain_count} · 已知 ${summary.known_duplicate_count}`
  }
  if (summary.cognitive_gain_count > 0) return `认知增量 ${summary.cognitive_gain_count}`
  if (summary.known_duplicate_count > 0) return `已知重复 ${summary.known_duplicate_count}`
  return '未发现新增'
}
</script>

<template>
  <section>
    <header class="page-header">
      <div>
        <p class="eyebrow">AI Reading Triage</p>
        <h1>内容 Inbox</h1>
        <p>这里会呈现值得精读、摘要即可和可以忽略的内容，同时保留认知探索。</p>
      </div>
      <span class="status-pill" :class="{ online: health.isSuccess.value }">
        {{ health.isSuccess.value ? 'API 已连接' : health.isPending.value ? '正在连接' : 'API 未连接' }}
      </span>
    </header>

    <div class="filter-row" aria-label="内容筛选">
      <button
        v-for="filter in filters"
        :key="filter.value"
        :class="{ active: activeFilter === filter.value }"
        @click="activeFilter = filter.value"
      >
        {{ filter.label }}
      </button>
    </div>

    <div v-if="contents.isPending.value" class="empty-state compact">
      <h2>正在加载内容…</h2>
    </div>

    <div v-else-if="contents.isError.value" class="empty-state compact error-panel">
      <h2>内容加载失败</h2>
      <p>{{ contents.error.value?.message }}</p>
      <button @click="contents.refetch()">重新加载</button>
    </div>

    <div v-else-if="filteredContents.length" class="content-list">
      <RouterLink
        v-for="item in filteredContents"
        :key="item.id"
        :to="`/contents/${item.id}`"
        class="content-card"
      >
        <div class="card-heading">
          <div>
            <span class="source-line">{{ item.source_type }} · {{ formatTime(item.created_at) }}</span>
            <h2>{{ item.title }}</h2>
          </div>
          <span class="analysis-status" :class="item.analysis_status">
            {{ analysisStatusText(item) }}
          </span>
        </div>
        <p>{{ item.one_sentence_summary || (item.queue.waiting_for_schedule ? '正文已保存，将在设定时段进行 AI 分诊。' : '正文已保存，等待 AI 分诊结果。') }}</p>
        <div class="card-footer">
          <span v-if="item.author">{{ item.author }}</span>
          <span>提取质量：{{ item.capture_quality }}</span>
          <span v-if="item.queue.next_eligible_at">
            下次整理：{{ formatTime(item.queue.next_eligible_at) }}
          </span>
          <span v-if="correctionText(item)" class="correction-tag">
            {{ correctionText(item) }}
          </span>
          <span v-else-if="item.recommendation" class="recommendation-tag">
            AI 建议：{{ recommendationText[item.recommendation] }}
          </span>
          <span v-if="item.discovery_type === 'outside_profile_high_value'" class="explore-tag">
            认知探索
          </span>
          <span v-if="item.delta_summary" class="delta-tag" :title="`召回上下文：${item.delta_summary.retrieval_context_status ?? '未知'}`">
            {{ deltaSummaryText(item.delta_summary) }}
          </span>
        </div>
      </RouterLink>
    </div>

    <div v-else class="empty-state">
      <span class="empty-icon">⌁</span>
      <h2>{{ (contents.data.value?.length || 0) ? '当前筛选下没有内容' : '等待第一篇内容' }}</h2>
      <p v-if="!(contents.data.value?.length || 0)">安装开发版插件，在网页上点击“提交 AI 分析”，内容就会进入这里。</p>
      <p v-else>切换到“全部”查看尚未完成 AI 分诊的内容。</p>
    </div>
  </section>
</template>
