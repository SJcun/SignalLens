<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { useRoute } from 'vue-router'

import { getContent } from '../api'

const route = useRoute()
const contentId = String(route.params.contentId)
const content = useQuery({
  queryKey: ['content', contentId],
  queryFn: () => getContent(contentId),
  refetchInterval: (query) => query.state.data?.analysis_status === 'completed' ? false : 5000,
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
          {{ content.data.value.analysis_status === 'pending' ? '等待分析' : content.data.value.analysis_status }}
        </span>
        <span>提取质量：{{ content.data.value.capture_quality }}</span>
        <a :href="content.data.value.source_url" target="_blank" rel="noreferrer">打开原文 ↗</a>
      </div>

      <div v-if="content.data.value.analysis_status !== 'completed'" class="pending-notice">
        正文已经成功导入。目前 Worker 尚未接入 AI 模型，因此分析状态会保持 pending。
      </div>

      <article class="detail-section">
        <h2>提取后的 Markdown</h2>
        <pre class="markdown-source">{{ content.data.value.markdown }}</pre>
      </article>
    </template>
  </section>
</template>
