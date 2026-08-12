<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'

import { getHealth } from '../api'

/** 首屏先验证 API 连接；内容列表将在分析 API 阶段接入。 */
const health = useQuery({ queryKey: ['health'], queryFn: getHealth, retry: 1 })
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
      <button class="active">全部</button>
      <button>推荐精读</button>
      <button>摘要即可</button>
      <button>选择性阅读</button>
      <button>可以忽略</button>
      <button>认知探索</button>
    </div>

    <div class="empty-state">
      <span class="empty-icon">⌁</span>
      <h2>等待第一篇内容</h2>
      <p>安装开发版插件，在网页上点击“提交 AI 分析”，内容就会进入这里。</p>
    </div>
  </section>
</template>

