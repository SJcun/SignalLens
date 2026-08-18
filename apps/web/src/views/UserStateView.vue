<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { reactive, watch } from 'vue'

import { getCurrentUserState, updateCurrentUserState } from '../api'

const queryClient = useQueryClient()
const state = useQuery({ queryKey: ['user-state'], queryFn: getCurrentUserState })

const form = reactive({
  active_goals: '',
  active_questions: '',
  focus_context: '',
  available_minutes: null as number | null,
  preferred_depth: null as 'quick' | 'balanced' | 'deep' | null,
  exploration_level: null as 'low' | 'medium' | 'high' | null,
  valid_until: '',
})

watch(
  () => state.data.value,
  (value) => {
    if (!value) return
    form.active_goals = value.active_goals.join('\n')
    form.active_questions = value.active_questions.join('\n')
    form.focus_context = value.focus_context ?? ''
    form.available_minutes = value.available_minutes
    form.preferred_depth = value.preferred_depth
    form.exploration_level = value.exploration_level
    form.valid_until = value.valid_until ? value.valid_until.slice(0, 16) : ''
  },
  { immediate: true },
)

const save = useMutation({
  mutationFn: () =>
    updateCurrentUserState({
      active_goals: splitList(form.active_goals),
      active_questions: splitList(form.active_questions),
      focus_context: form.focus_context.trim() || null,
      available_minutes: form.available_minutes,
      preferred_depth: form.preferred_depth,
      exploration_level: form.exploration_level,
      valid_until: form.valid_until ? new Date(form.valid_until).toISOString() : null,
    }),
  onSuccess: async () => {
    await queryClient.invalidateQueries({ queryKey: ['user-state'] })
  },
})

function splitList(value: string): string[] {
  return value
    .split(/\n/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 10)
}
</script>

<template>
  <section>
    <p class="eyebrow">Current User State</p>
    <h1>当前阅读状态</h1>
    <p class="page-intro">
      只描述你此刻为什么读、关注什么、能投入多少时间；有效期过后按未设置处理，回退到长期画像。
      这里不承担长期认知存储，也不会根据浏览行为自动改变。
    </p>

    <div v-if="state.isPending.value" class="panel">正在加载当前状态…</div>
    <div v-else-if="state.isError.value" class="panel error-panel">
      {{ state.error.value?.message }}
    </div>

    <form v-else class="questionnaire" @submit.prevent="save.mutate()">
      <fieldset :disabled="save.isPending.value">
        <legend>此刻的阅读上下文</legend>
        <label>
          当前目标（每行一个）
          <textarea v-model="form.active_goals" rows="3" maxlength="1000" />
        </label>
        <label>
          当前关注的问题（每行一个）
          <textarea v-model="form.active_questions" rows="3" maxlength="1000" />
        </label>
        <label>
          上下文描述
          <input v-model="form.focus_context" maxlength="500" />
        </label>
        <div class="feedback-grid">
          <label>
            可投入时间（分钟）
            <input v-model.number="form.available_minutes" type="number" min="1" max="480" />
          </label>
          <label>
            当前阅读深度
            <select v-model="form.preferred_depth">
              <option :value="null">不指定</option>
              <option value="quick">快速浏览</option>
              <option value="balanced">平衡</option>
              <option value="deep">深入精读</option>
            </select>
          </label>
          <label>
            当前探索意愿
            <select v-model="form.exploration_level">
              <option :value="null">不指定</option>
              <option value="low">低</option>
              <option value="medium">中</option>
              <option value="high">高</option>
            </select>
          </label>
          <label>
            状态有效期（留空表示长期有效）
            <input v-model="form.valid_until" type="datetime-local" />
          </label>
        </div>
      </fieldset>
      <div class="form-actions">
        <button class="primary-button" type="submit" :disabled="save.isPending.value">
          {{ save.isPending.value ? '正在保存…' : '保存当前状态' }}
        </button>
        <span v-if="save.isSuccess.value" class="success-text">当前状态已保存。</span>
        <span v-if="save.isError.value" class="error-text">{{ save.error.value?.message }}</span>
      </div>
    </form>
  </section>
</template>
