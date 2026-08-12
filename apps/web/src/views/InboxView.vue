<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'

import { getContents, getHealth, type ContentSummary } from '../api'

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
  { value: 'deep_read', label: '推荐精读' },
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

/** 使用用户本地时区展示采集时间。 */
function formatTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
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
            {{ statusText[item.analysis_status] }}
          </span>
        </div>
        <p>{{ item.one_sentence_summary || '正文已保存，等待 AI 分诊结果。' }}</p>
        <div class="card-footer">
          <span v-if="item.author">{{ item.author }}</span>
          <span>提取质量：{{ item.capture_quality }}</span>
          <span v-if="item.discovery_type === 'outside_profile_high_value'" class="explore-tag">
            认知探索
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
