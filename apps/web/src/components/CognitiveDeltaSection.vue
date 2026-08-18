<script setup lang="ts">
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'

import {
  submitClaimCorrection,
  submitClaimFeedback,
  type CognitiveDelta,
  type CompareRelation,
  type ContentClaim,
  type MemoryStance,
  type PrimaryRelation,
} from '../api'

const props = defineProps<{
  contentId: string
  analysisId: string
  claims: ContentClaim[]
  delta: CognitiveDelta
}>()

const queryClient = useQueryClient()
// 默认折叠的高级纠错入口；只有展开解释时才显示，普通阅读反馈不增加必填项。
const expandedCorrection = ref<string | null>(null)
// Claim 级轻量反馈的成功提示，用后自动消失。
const feedbackMessage = ref<{ claimId: string; text: string } | null>(null)

const relationText: Record<PrimaryRelation, string> = {
  duplicate: '你已经知道',
  extends: '扩展已有认识',
  complements: '补充其他角度',
  contradicts: '与已有认识冲突',
  updates: '旧信息更新',
  new: '本文真正新增',
}

const roleText = { core: '核心', supporting: '重要支撑', detail: '边缘细节' } as const

const stanceOptions: Array<{ value: MemoryStance; label: string }> = [
  { value: 'accept', label: '我认同' },
  { value: 'reject', label: '我不认同' },
  { value: 'mixed', label: '部分认同' },
  { value: 'undecided', label: '尚未决定' },
  { value: 'not_applicable', label: '不适用' },
]

const retrievalContextText: Record<string, { label: string; hint: string }> = {
  sufficient: { label: '本次召回上下文完整', hint: '比较基于全部可用记忆候选完成。' },
  partial: { label: '本次召回上下文有限', hint: '部分内容按“相对已记录认知未找到对应项”表达，不代表你绝对不知道。' },
  insufficient: { label: '本次召回上下文不足', hint: '没有可用的认知记忆或召回不完整，系统未断言你已知或未知任何内容。' },
}

/** 逐 Claim 关系：展示应用纠错后的 effective 值，原始值保留在纠错记录中。 */
const relationsByClaim = computed(() => {
  const byClaim = new Map<string, CompareRelation>()
  for (const relation of props.delta.effective_relations) {
    byClaim.set(relation.current_claim_id, relation)
  }
  return byClaim
})

/** 召回上下文状态由代码计算；未知值时按保守提示展示。 */
const retrievalStatus = computed(() => String(props.delta.retrieval_context.status ?? ''))

/** 按“已知重复 / 认知增量 / 冲突 / 更新”分组展示，避免堆叠复杂关系图。 */
const groupedClaims = computed(() => {
  const groups: Array<{ relation: PrimaryRelation; claims: ContentClaim[] }> = []
  const order: PrimaryRelation[] = [
    'duplicate',
    'new',
    'extends',
    'complements',
    'contradicts',
    'updates',
  ]
  for (const relation of order) {
    const claims = props.claims.filter(
      (claim) =>
        claim.claim_id != null && relationsByClaim.value.get(claim.claim_id)?.primary_relation === relation,
    )
    if (claims.length) groups.push({ relation, claims })
  }
  return groups
})

const feedback = useMutation({
  mutationFn: ({
    claimId,
    awareness,
    stance,
    confirmationType,
  }: {
    claimId: string
    awareness?: 'known' | 'uncertain'
    stance?: MemoryStance
    confirmationType?: 'already_known' | 'learned_now' | 'awareness_confirmed' | 'stance_confirmed'
  }) =>
    submitClaimFeedback(props.analysisId, claimId, {
      awareness: awareness ?? null,
      stance: stance ?? null,
      confirmation_type: confirmationType ?? null,
    }),
  onSuccess: async (_result, variables) => {
    await queryClient.invalidateQueries({ queryKey: ['content', props.contentId] })
    feedbackMessage.value = { claimId: variables.claimId, text: '已记录你的确认' }
    setTimeout(() => {
      feedbackMessage.value = null
    }, 3000)
  },
})

const correction = useMutation({
  mutationFn: (payload: {
    claimId: string
    correction_type: 'primary_relation' | 'claim_role'
    corrected_value: string
  }) => submitClaimCorrection(props.analysisId, payload.claimId, payload),
  onSuccess: async () => {
    expandedCorrection.value = null
    await queryClient.invalidateQueries({ queryKey: ['content', props.contentId] })
  },
})

function relationOf(claim: ContentClaim): PrimaryRelation {
  return relationsByClaim.value.get(claim.claim_id ?? '')?.primary_relation ?? 'new'
}
</script>

<template>
  <article class="detail-section result-section">
    <div class="section-heading">
      <div>
        <p class="eyebrow">Cognitive Delta</p>
        <h2>与已有认识的差异</h2>
      </div>
      <span
        v-if="retrievalStatus"
        class="delta-status"
        :class="retrievalStatus"
        :title="retrievalContextText[retrievalStatus]?.hint"
      >
        {{ retrievalContextText[retrievalStatus]?.label ?? '召回状态未知' }}
      </span>
    </div>
    <p class="delta-hint">
      “新增”表示在本次可用、已确认且成功召回的认知记忆中没有对应项，不代表你绝对不知道。
    </p>

    <div v-for="group in groupedClaims" :key="group.relation" class="result-block">
      <h2>{{ relationText[group.relation] }}（{{ group.claims.length }}）</h2>
      <ul class="delta-claim-list">
        <li v-for="claim in group.claims" :key="claim.claim_id ?? claim.claim">
          <div class="delta-claim-head">
            <strong>{{ claim.claim }}</strong>
            <span class="claim-role-tag" :class="claim.claim_role">
              {{ roleText[claim.claim_role] }}
            </span>
            <button
              class="link-button"
              type="button"
              @click="expandedCorrection = expandedCorrection === claim.claim_id ? null : (claim.claim_id ?? '')"
            >
              为什么这样判断？
            </button>
          </div>
          <p v-if="relationsByClaim.get(claim.claim_id ?? '')?.reason" class="delta-claim-reason">
            {{ relationsByClaim.get(claim.claim_id ?? '')?.reason }}
          </p>
          <p
            v-if="relationsByClaim.get(claim.claim_id ?? '')?.conflict_summary"
            class="delta-conflict"
          >
            冲突说明：{{ relationsByClaim.get(claim.claim_id ?? '')?.conflict_summary }}
          </p>

          <div class="claim-feedback-row">
            <span class="claim-feedback-label">这个知识点：</span>
            <button
              type="button"
              @click="feedback.mutate({ claimId: claim.claim_id!, awareness: 'known', confirmationType: 'already_known' })"
            >
              我早已知道
            </button>
            <button
              type="button"
              @click="feedback.mutate({ claimId: claim.claim_id!, awareness: 'known', confirmationType: 'learned_now' })"
            >
              这次新学到
            </button>
            <button type="button" @click="feedback.mutate({ claimId: claim.claim_id!, awareness: 'uncertain' })">
              我还不确定是否理解
            </button>
            <span v-for="option in stanceOptions" :key="option.value">
              <button type="button" @click="feedback.mutate({ claimId: claim.claim_id!, stance: option.value })">
                {{ option.label }}
              </button>
            </span>
          </div>
          <p v-if="feedbackMessage?.claimId === claim.claim_id" class="feedback-ok">
            {{ feedbackMessage.text }}
          </p>

          <div v-if="expandedCorrection === claim.claim_id" class="advanced-correction">
            <p class="advanced-correction-title">高级纠错（原始值与纠正值都会保留）</p>
            <label>
              实际关系：
              <select
                :value="relationOf(claim)"
                @change="
                  correction.mutate({
                    claimId: claim.claim_id!,
                    correction_type: 'primary_relation',
                    corrected_value: ($event.target as HTMLSelectElement).value,
                  })
                "
              >
                <option value="duplicate">重复</option>
                <option value="extends">扩展</option>
                <option value="complements">补充</option>
                <option value="contradicts">冲突</option>
                <option value="updates">更新</option>
                <option value="new">全新</option>
              </select>
            </label>
            <label>
              该 Claim 在文章中的角色：
              <select
                :value="claim.claim_role"
                @change="
                  correction.mutate({
                    claimId: claim.claim_id!,
                    correction_type: 'claim_role',
                    corrected_value: ($event.target as HTMLSelectElement).value,
                  })
                "
              >
                <option value="core">核心</option>
                <option value="supporting">重要支撑</option>
                <option value="detail">边缘细节</option>
              </select>
            </label>
            <p v-if="correction.isError.value" class="error-text">
              {{ correction.error.value?.message }}
            </p>
          </div>
        </li>
      </ul>
    </div>

    <p v-if="!groupedClaims.length" class="delta-empty">没有可展示的认知差异。</p>
  </article>
</template>
