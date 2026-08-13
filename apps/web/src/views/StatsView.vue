<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import {
  decideCalibrationSuggestion,
  getCalibrationStats,
  type Recommendation,
} from '../api'

const recommendationLevels: Array<{ value: Recommendation; label: string }> = [
  { value: 'ignore', label: '可以忽略' },
  { value: 'summary_enough', label: '摘要即可' },
  { value: 'selective_read', label: '选择性阅读' },
  { value: 'deep_read', label: '全文精读' },
]

const queryClient = useQueryClient()
const stats = useQuery({
  queryKey: ['calibration-stats'],
  queryFn: getCalibrationStats,
})
const decideSuggestion = useMutation({
  mutationFn: ({ id, decision }: { id: string; decision: 'accepted' | 'rejected' }) =>
    decideCalibrationSuggestion(id, decision),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['calibration-stats'] }),
})

/** 获取四级混淆矩阵中的计数，缺失组合按零展示。 */
function matrixCount(ai: Recommendation, user: Recommendation): number {
  return stats.data.value?.confusion_matrix.find(
    (item) => item.ai_recommendation === ai && item.user_recommendation === user,
  )?.count || 0
}
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

      <article class="calibration-panel">
        <h2>AI 建议 → 用户最终等级</h2>
        <p>行是 AI 原建议，列是你阅读后选择的最合适等级。</p>
        <div class="matrix-scroll">
          <table class="matrix-table">
            <thead>
              <tr>
                <th>AI \ 用户</th>
                <th v-for="level in recommendationLevels" :key="level.value">
                  {{ level.label }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="aiLevel in recommendationLevels" :key="aiLevel.value">
                <th>{{ aiLevel.label }}</th>
                <td v-for="userLevel in recommendationLevels" :key="userLevel.value">
                  {{ matrixCount(aiLevel.value, userLevel.value) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p>
          相邻一级偏差 {{ stats.data.value.adjacent_error_count }} 次；跨两级及以上严重偏差
          {{ stats.data.value.major_error_count }} 次。
        </p>
      </article>

      <article class="calibration-panel">
        <h2>下一版阅读规则候选</h2>
        <div v-if="stats.data.value.feedback_needed > 0" class="pending-notice">
          还需 {{ stats.data.value.feedback_needed }} 条包含明确用户等级的反馈，才开始提出系统性规则调整建议。
        </div>
        <p v-else-if="!stats.data.value.suggestions.length">
          已达到评测门槛，暂未发现达到阈值的系统性偏差。继续积累反馈即可。
        </p>
        <div v-else class="suggestion-list">
          <section v-for="suggestion in stats.data.value.suggestions" :key="suggestion.id">
            <div class="section-heading">
              <h3>{{ suggestion.title }}</h3>
              <span class="saved-badge">
                {{ suggestion.status === 'accepted' ? '已接受' : suggestion.status === 'rejected' ? '已拒绝' : '待确认' }}
              </span>
            </div>
            <p>{{ suggestion.evidence }}</p>
            <strong>候选规则：{{ suggestion.proposed_rule }}</strong>
            <div class="form-actions">
              <button
                class="primary-button"
                type="button"
                :disabled="decideSuggestion.isPending.value"
                @click="decideSuggestion.mutate({ id: suggestion.id, decision: 'accepted' })"
              >接受为下一版候选</button>
              <button
                class="secondary-button"
                type="button"
                :disabled="decideSuggestion.isPending.value"
                @click="decideSuggestion.mutate({ id: suggestion.id, decision: 'rejected' })"
              >拒绝</button>
            </div>
          </section>
        </div>
        <p class="muted">确认只记录规则候选，不会自动训练模型、修改画像或直接改写当前 Prompt。</p>
      </article>

      <div v-if="!stats.data.value.questionnaire_completed" class="pending-notice">
        初始画像尚未填写。先完成阅读偏好问卷，后续分析才能进行真正的个性化比较。
      </div>
    </template>
  </section>
</template>
