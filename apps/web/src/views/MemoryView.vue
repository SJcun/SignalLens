<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { reactive, ref } from 'vue'

import {
  appendMemoryRevision,
  createMemoryEntry,
  decideMemoryProposal,
  getMemory,
  getMemories,
  getMemoryProposals,
  type AwarenessState,
  type MemoryProposal,
  type MemoryStance,
  type MemorySummary,
} from '../api'

const queryClient = useQueryClient()
const memories = useQuery({ queryKey: ['memories'], queryFn: getMemories })
const proposals = useQuery({ queryKey: ['memory-proposals'], queryFn: getMemoryProposals })
const expandedMemoryId = ref<string | null>(null)
const expandedMemory = useQuery({
  queryKey: ['memory', expandedMemoryId.value],
  queryFn: () => getMemory(expandedMemoryId.value!),
  enabled: () => expandedMemoryId.value != null,
})

const awarenessText: Record<AwarenessState, string> = { known: '已知', uncertain: '未确认' }
const stanceText: Record<MemoryStance, string> = {
  accept: '认同',
  reject: '反对',
  mixed: '部分认同',
  undecided: '尚未决定',
  not_applicable: '不适用',
}
const lifecycleText = { active: '有效', obsolete: '过时' }

const createForm = reactive({
  statement: '',
  awareness_state: 'known' as AwarenessState,
  stance: 'accept' as MemoryStance,
  topics: '',
  entities: '',
})
const createResult = ref<string | null>(null)
const create = useMutation({
  mutationFn: () =>
    createMemoryEntry({
      statement: createForm.statement,
      awareness_state: createForm.awareness_state,
      stance: createForm.stance,
      topics: splitList(createForm.topics),
      entities: splitList(createForm.entities),
    }),
  onSuccess: async (result) => {
    createResult.value =
      result.outcome === 'confirmed'
        ? '该认知已存在且状态未变，只追加了确认记录。'
        : result.outcome === 'revised'
          ? '已追加新版本。'
          : result.outcome === 'proposal'
            ? '匹配结果不确定，已生成待确认建议，请在下方向处理。'
            : '已创建新的认知记忆。'
    createForm.statement = ''
    createForm.topics = ''
    createForm.entities = ''
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['memories'] }),
      queryClient.invalidateQueries({ queryKey: ['memory-proposals'] }),
    ])
  },
})

function splitList(value: string): string[] {
  return value
    .split(/[,，、\n]/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 10)
}

async function toggleMemory(memory: MemorySummary): Promise<void> {
  if (expandedMemoryId.value === memory.id) {
    expandedMemoryId.value = null
    return
  }
  expandedMemoryId.value = memory.id
  queryClient.invalidateQueries({ queryKey: ['memory', memory.id] })
}

const reviseForm = reactive({
  statement: '',
  awareness_state: null as AwarenessState | null,
  stance: null as MemoryStance | null,
  lifecycle: null as 'active' | 'obsolete' | null,
})
const reviseTargetId = ref<string | null>(null)
const revise = useMutation({
  mutationFn: (memoryId: string) => {
    const target = memories.data.value?.find((item) => item.id === memoryId)
    return appendMemoryRevision(memoryId, {
      expected_current_revision_id: target!.current_revision!.id,
      statement: reviseForm.statement || null,
      awareness_state: reviseForm.awareness_state,
      stance: reviseForm.stance,
      lifecycle: reviseForm.lifecycle,
    })
  },
  onSuccess: async () => {
    reviseTargetId.value = null
    reviseForm.statement = ''
    reviseForm.awareness_state = null
    reviseForm.stance = null
    reviseForm.lifecycle = null
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['memories'] }),
      queryClient.invalidateQueries({ queryKey: ['memory', expandedMemoryId.value] }),
    ])
  },
})

const proposalDecision = useMutation({
  mutationFn: ({
    proposal,
    decision,
    mergeMemoryId,
  }: {
    proposal: MemoryProposal
    decision: 'accepted' | 'rejected'
    mergeMemoryId?: string
  }) => decideMemoryProposal(proposal.id, decision, mergeMemoryId),
  onSuccess: async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['memory-proposals'] }),
      queryClient.invalidateQueries({ queryKey: ['memories'] }),
    ])
  },
})

function formatTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: '2-digit',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
</script>

<template>
  <section>
    <p class="eyebrow">Cognitive Memory</p>
    <h1>认知记忆</h1>
    <p class="page-intro">
      这里只保存你明确确认的紧凑认知状态，不做文章收藏，也不根据浏览行为自动推断。
      知晓状态与观点立场分开保存：知道但反对是合法状态。
    </p>

    <div v-if="memories.isPending.value" class="panel">正在加载认知记忆…</div>
    <div v-else-if="memories.isError.value" class="panel error-panel">
      {{ memories.error.value?.message }}
    </div>

    <template v-else>
      <form class="questionnaire" @submit.prevent="create.mutate()">
        <fieldset :disabled="create.isPending.value">
          <legend>手工录入认知</legend>
          <p>录入前会先做 Memory Match；等价且状态未变时只追加确认记录。</p>
          <label>
            知识点
            <textarea v-model="createForm.statement" required maxlength="2000" rows="2" />
          </label>
          <div class="feedback-grid">
            <label>
              知晓状态
              <select v-model="createForm.awareness_state">
                <option value="known">已知</option>
                <option value="uncertain">未确认</option>
              </select>
            </label>
            <label>
              观点立场
              <select v-model="createForm.stance">
                <option value="accept">认同</option>
                <option value="reject">反对</option>
                <option value="mixed">部分认同</option>
                <option value="undecided">尚未决定</option>
                <option value="not_applicable">不适用</option>
              </select>
            </label>
          </div>
          <label>
            主题（逗号分隔）
            <input v-model="createForm.topics" maxlength="500" />
          </label>
          <label>
            实体（逗号分隔）
            <input v-model="createForm.entities" maxlength="500" />
          </label>
        </fieldset>
        <div class="form-actions">
          <button class="primary-button" type="submit" :disabled="create.isPending.value">
            {{ create.isPending.value ? '正在匹配…' : '录入认知' }}
          </button>
          <span v-if="create.isSuccess.value" class="success-text">{{ createResult }}</span>
          <span v-if="create.isError.value" class="error-text">{{ create.error.value?.message }}</span>
        </div>
      </form>

      <section v-if="proposals.data.value?.length" class="detail-section">
        <p class="eyebrow">Pending Proposals</p>
        <h2>待确认修改建议</h2>
        <p>未确认的建议不会参与正式分析；拒绝记录会保留，防止系统反复提出同一建议。</p>
        <div v-for="proposal in proposals.data.value" :key="proposal.id" class="proposal-card">
          <div>
            <strong>{{ proposal.proposed_statement || '（未提供内容）' }}</strong>
            <p v-if="proposal.reason" class="muted-text">{{ proposal.reason }}</p>
            <p class="muted-text">
              动作：{{ proposal.action }}
              <span v-if="proposal.candidate_memory_revision_ids.length">
                ｜候选：{{ proposal.candidate_memory_revision_ids.length }} 条
              </span>
            </p>
          </div>
          <div class="proposal-actions">
            <button class="secondary-button" @click="proposalDecision.mutate({ proposal, decision: 'rejected' })">
              拒绝
            </button>
            <button
              v-if="proposal.action === 'RESOLVE_MATCH'"
              class="primary-button"
              @click="proposalDecision.mutate({ proposal, decision: 'accepted' })"
            >
              仍然创建新项
            </button>
          </div>
          <div
            v-if="proposal.action === 'RESOLVE_MATCH' && proposal.candidate_memory_revision_ids.length"
            class="proposal-merge-targets"
          >
            <span class="muted-text">合并到现有项：</span>
            <button
              v-for="memory in memories.data.value"
              :key="memory.id"
              v-show="
                memory.current_revision
                && proposal.candidate_memory_revision_ids.includes(memory.current_revision.id)
              "
              type="button"
              class="secondary-button"
              @click="proposalDecision.mutate({ proposal, decision: 'accepted', mergeMemoryId: memory.id })"
            >
              {{ memory.current_revision?.statement.slice(0, 30) }}
            </button>
          </div>
        </div>
        <p v-if="proposalDecision.isError.value" class="error-text">
          {{ proposalDecision.error.value?.message }}
        </p>
      </section>

      <section class="detail-section">
        <p class="eyebrow">Confirmed Memories</p>
        <h2>已确认认知（{{ memories.data.value?.length ?? 0 }}）</h2>
        <div v-if="!memories.data.value?.length" class="muted-text">
          还没有已确认的认知。阅读文章时对 Claim 的确认会出现在这里。
        </div>
        <div
          v-for="memory in memories.data.value"
          :key="memory.id"
          class="memory-card"
          :class="{ expanded: expandedMemoryId === memory.id }"
        >
          <button class="memory-card-head" type="button" @click="toggleMemory(memory)">
            <div>
              <strong>{{ memory.current_revision?.statement }}</strong>
              <p class="muted-text">
                <span class="memory-tag">{{ awarenessText[memory.current_revision?.awareness_state ?? 'uncertain'] }}</span>
                <span class="memory-tag">{{ stanceText[memory.current_revision?.stance ?? 'not_applicable'] }}</span>
                <span class="memory-tag">{{ lifecycleText[memory.current_revision?.lifecycle ?? 'active'] }}</span>
                共 {{ memory.revision_count }} 个版本
              </p>
            </div>
            <span>{{ expandedMemoryId === memory.id ? '收起' : '展开' }}</span>
          </button>

          <div v-if="expandedMemoryId === memory.id" class="memory-detail">
            <div v-if="expandedMemory.isPending.value" class="muted-text">正在加载…</div>
            <template v-else-if="expandedMemory.data.value">
              <div v-if="expandedMemory.data.value.current_revision" class="memory-revise">
                <h3>修改本条认知</h3>
                <div class="feedback-grid">
                  <label>
                    知晓状态
                    <select v-model="reviseForm.awareness_state">
                      <option :value="null">保持不变</option>
                      <option value="known">已知</option>
                      <option value="uncertain">未确认</option>
                    </select>
                  </label>
                  <label>
                    观点立场
                    <select v-model="reviseForm.stance">
                      <option :value="null">保持不变</option>
                      <option value="accept">认同</option>
                      <option value="reject">反对</option>
                      <option value="mixed">部分认同</option>
                      <option value="undecided">尚未决定</option>
                      <option value="not_applicable">不适用</option>
                    </select>
                  </label>
                  <label>
                    有效状态
                    <select v-model="reviseForm.lifecycle">
                      <option :value="null">保持不变</option>
                      <option value="active">有效</option>
                      <option value="obsolete">过时</option>
                    </select>
                  </label>
                </div>
                <label>
                  更新表述（留空保持当前版本）
                  <textarea v-model="reviseForm.statement" maxlength="2000" rows="2" />
                </label>
                <button class="secondary-button" @click="revise.mutate(memory.id)">
                  追加新版本
                </button>
                <p v-if="revise.isError.value" class="error-text">{{ revise.error.value?.message }}</p>
              </div>

              <h3>版本历史</h3>
              <div v-for="revision in expandedMemory.data.value.revisions" :key="revision.id" class="revision-row">
                <div>
                  <strong>v{{ revision.version }}：{{ revision.statement }}</strong>
                  <p class="muted-text">
                    {{ awarenessText[revision.awareness_state] }}｜{{ stanceText[revision.stance] }}｜
                    {{ lifecycleText[revision.lifecycle] }}｜{{ revision.source_type }}｜{{ formatTime(revision.created_at) }}
                  </p>
                </div>
              </div>

              <h3>确认记录</h3>
              <div v-if="!expandedMemory.data.value.confirmation_events.length" class="muted-text">
                暂无确认记录。
              </div>
              <p v-for="event in expandedMemory.data.value.confirmation_events" :key="event.id" class="muted-text">
                {{ event.confirmation_type }}（{{ event.source_type }}）{{ formatTime(event.created_at) }}
              </p>
            </template>
          </div>
        </div>
      </section>
    </template>
  </section>
</template>
