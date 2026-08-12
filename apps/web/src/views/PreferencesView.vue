<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { reactive, ref, watch } from 'vue'

import {
  getProfile,
  updateProfile,
  type ProfileUpdate,
} from '../api'

const queryClient = useQueryClient()
const profile = useQuery({ queryKey: ['profile'], queryFn: getProfile })
const focusTopicsText = ref('')
const form = reactive<ProfileUpdate>({
  focus_topics: [],
  known_topics: [],
  reading_goals: [],
  preferred_depth: 'balanced',
  time_budget_minutes: 20,
  exploration_level: 'medium',
  evaluation_mode: true,
})

watch(
  () => profile.data.value,
  (value) => {
    if (!value) return
    focusTopicsText.value = value.focus_topics.join('、')
    Object.assign(form, {
      focus_topics: [...value.focus_topics],
      known_topics: value.known_topics.map((item) => ({ ...item })),
      reading_goals: [...value.reading_goals],
      preferred_depth: value.preferred_depth,
      time_budget_minutes: value.time_budget_minutes,
      exploration_level: value.exploration_level,
      evaluation_mode: value.evaluation_mode,
    })
  },
  { immediate: true },
)

const save = useMutation({
  mutationFn: () => {
    form.focus_topics = focusTopicsText.value
      .split(/[、,，\n]/)
      .map((item) => item.trim())
      .filter(Boolean)
      .slice(0, 5)
    return updateProfile({
      ...form,
      known_topics: form.known_topics.map((item) => ({ ...item })),
      reading_goals: [...form.reading_goals],
    })
  },
  onSuccess: async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['profile'] }),
      queryClient.invalidateQueries({ queryKey: ['calibration-stats'] }),
    ])
  },
})

/** 添加一行熟悉领域，熟悉程度必须由用户明确选择。 */
function addKnownTopic(): void {
  form.known_topics.push({ topic: '', level: 'intermediate' })
}

function removeKnownTopic(index: number): void {
  form.known_topics.splice(index, 1)
}

const readingGoalOptions = [
  { value: 'solve_problems', label: '解决工作或实际问题' },
  { value: 'systematic_learning', label: '系统学习一个领域' },
  { value: 'follow_updates', label: '了解行业和技术动态' },
  { value: 'explore', label: '跨领域探索' },
]
</script>

<template>
  <section>
    <p class="eyebrow">Profile</p>
    <h1>阅读偏好</h1>
    <p class="page-intro">用 3 分钟建立低置信度初始画像。这里只记录你的明确选择，不会根据一次反馈自动改变兴趣。</p>

    <div v-if="profile.isPending.value" class="panel">正在加载问卷…</div>
    <div v-else-if="profile.isError.value" class="panel error-panel">
      {{ profile.error.value?.message }}
    </div>
    <form v-else class="questionnaire" @submit.prevent="save.mutate()">
      <fieldset>
        <legend>1. 当前重点关注什么？</legend>
        <p>最多 5 个主题，用逗号或顿号分隔。</p>
        <input v-model="focusTopicsText" required placeholder="例如：AI 工程、软件架构、个人知识管理" />
      </fieldset>

      <fieldset>
        <legend>2. 已经熟悉哪些领域？</legend>
        <p>兴趣和知识状态分开记录；不熟悉的主题不等于没有价值。</p>
        <div v-for="(item, index) in form.known_topics" :key="index" class="known-topic-row">
          <input v-model="item.topic" required placeholder="领域名称" />
          <select v-model="item.level">
            <option value="basic">基础了解</option>
            <option value="intermediate">比较熟悉</option>
            <option value="advanced">深入掌握</option>
          </select>
          <button type="button" class="secondary-button" @click="removeKnownTopic(index)">移除</button>
        </div>
        <button type="button" class="secondary-button" @click="addKnownTopic">添加熟悉领域</button>
      </fieldset>

      <fieldset>
        <legend>3. 当前阅读目标</legend>
        <label v-for="option in readingGoalOptions" :key="option.value" class="choice-row">
          <input v-model="form.reading_goals" type="checkbox" :value="option.value" />
          <span>{{ option.label }}</span>
        </label>
      </fieldset>

      <div class="question-grid">
        <fieldset>
          <legend>4. 偏好的阅读深度</legend>
          <select v-model="form.preferred_depth">
            <option value="quick">尽量快速，只看必要信息</option>
            <option value="balanced">效率与深度平衡</option>
            <option value="deep">愿意为高价值内容深入阅读</option>
          </select>
        </fieldset>

        <fieldset>
          <legend>单篇可投入时间</legend>
          <div class="number-field">
            <input v-model.number="form.time_budget_minutes" type="number" min="5" max="120" required />
            <span>分钟</span>
          </div>
        </fieldset>

        <fieldset>
          <legend>5. 跨领域探索比例</legend>
          <select v-model="form.exploration_level">
            <option value="low">较低：主要聚焦当前目标</option>
            <option value="medium">适中：保留少量边界内容</option>
            <option value="high">较高：主动寻找新视角</option>
          </select>
        </fieldset>
      </div>

      <label class="evaluation-toggle">
        <input v-model="form.evaluation_mode" type="checkbox" />
        <span>
          <strong>开启评测模式</strong>
          <small>阅读完成后优先提示提交简短评价；满意后可手动关闭，普通反馈入口仍保留。</small>
        </span>
      </label>

      <div class="form-actions">
        <button class="primary-button" type="submit" :disabled="save.isPending.value">
          {{ save.isPending.value ? '正在保存…' : profile.data.value?.questionnaire_completed ? '保存修改' : '完成初始问卷' }}
        </button>
        <span v-if="save.isSuccess.value" class="success-text">已保存，后续新分析会使用这份画像。</span>
        <span v-if="save.isError.value" class="error-text">{{ save.error.value?.message }}</span>
      </div>
    </form>
  </section>
</template>
