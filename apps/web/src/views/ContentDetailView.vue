<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <section>
    <p class="eyebrow">Content Analysis</p>
    <h1>内容分析</h1>
    <p class="muted">内容 ID：{{ route.params.contentId }}</p>
    <div class="panel">
      <h2>分析结果将在这里展示</h2>
      <p>包括阅读建议、新增信息、核心观点、真实分歧以及章节级阅读计划。</p>
    </div>
  </section>
</template>

