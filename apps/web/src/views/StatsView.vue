<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'

import { getCalibrationStats } from '../api'

const stats = useQuery({
  queryKey: ['calibration-stats'],
  queryFn: getCalibrationStats,
})
</script>

<template>
  <section>
    <p class="eyebrow">Calibration</p>
    <h1>分诊校准</h1>
    <p class="page-intro">这里比较 AI 当时的判断和你的阅读后评价，不会自动改写用户画像。</p>

    <div v-if="stats.isPending.value" class="panel">正在加载校准数据…</div>
    <div v-else-if="stats.isError.value" class="panel error-panel">
      {{ stats.error.value?.message }}
    </div>
    <template v-else-if="stats.data.value">
      <div class="mode-banner" :class="{ inactive: !stats.data.value.evaluation_mode }">
        <div>
          <strong>{{ stats.data.value.evaluation_mode ? '评测模式已开启' : '评测模式已关闭' }}</strong>
          <p>
            {{ stats.data.value.evaluation_mode
              ? '继续在阅读完成后评价 AI 建议，逐步积累真实回归数据。'
              : '详情页仍保留普通反馈入口，需要集中校准时可在阅读偏好中重新开启。' }}
          </p>
        </div>
        <RouterLink to="/preferences">调整设置</RouterLink>
      </div>

      <div class="metric-grid calibration-grid">
        <article><strong>{{ stats.data.value.completed_analyses }}</strong><span>已完成分析</span></article>
        <article><strong>{{ stats.data.value.feedback_count }}</strong><span>有效人工评价</span></article>
        <article>
          <strong>{{ stats.data.value.accuracy_rate === null ? '—' : `${stats.data.value.accuracy_rate}%` }}</strong>
          <span>推荐准确率</span>
        </article>
        <article class="danger-metric">
          <strong>{{ stats.data.value.high_value_miss_count }}</strong>
          <span>高价值误杀</span>
        </article>
      </div>

      <div class="calibration-details">
        <article>
          <h2>推荐偏差</h2>
          <dl>
            <div><dt>准确</dt><dd>{{ stats.data.value.accurate_count }}</dd></div>
            <div><dt>建议偏高</dt><dd>{{ stats.data.value.too_high_count }}</dd></div>
            <div><dt>建议偏低</dt><dd>{{ stats.data.value.too_low_count }}</dd></div>
          </dl>
        </article>
        <article>
          <h2>摘要质量</h2>
          <strong>{{ stats.data.value.summary_issue_count }}</strong>
          <p>次被标记为存在遗漏或误导。后续优化应优先回看这些原始反馈。</p>
        </article>
      </div>

      <div v-if="!stats.data.value.questionnaire_completed" class="pending-notice">
        初始画像尚未填写。先完成阅读偏好问卷，后续分析才能进行真正的个性化比较。
      </div>
    </template>
  </section>
</template>
