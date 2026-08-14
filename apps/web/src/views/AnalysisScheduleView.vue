<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'

import {
  getAnalysisSchedule,
  updateAnalysisSchedule,
  type AnalysisWindow,
} from '../api'

const queryClient = useQueryClient()
const schedule = useQuery({
  queryKey: ['analysis-schedule'],
  queryFn: getAnalysisSchedule,
})
const enabled = ref(false)
const windows = ref<AnalysisWindow[]>([])

watch(
  () => schedule.data.value,
  (value) => {
    if (!value) return
    enabled.value = value.enabled
    windows.value = value.windows.map((item) => ({ ...item }))
  },
  { immediate: true },
)

const save = useMutation({
  mutationFn: updateAnalysisSchedule,
  onSuccess: async (value) => {
    enabled.value = value.enabled
    windows.value = value.windows.map((item) => ({ ...item }))
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['analysis-schedule'] }),
      queryClient.invalidateQueries({ queryKey: ['contents'] }),
    ])
  },
})

const nextWindowText = computed(() => {
  const value = schedule.data.value?.next_window_start
  if (!value) return null
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
})

/** 总开关即时保存；高价时段释放等待队列前要求用户确认费用影响。 */
function toggleEnabled(event: Event): void {
  const target = event.target as HTMLInputElement
  const nextEnabled = target.checked
  const current = schedule.data.value
  if (
    !nextEnabled
    && current?.enabled
    && !current.currently_allowed
    && current.scheduled_job_count > 0
    && !window.confirm(
      `当前有 ${current.scheduled_job_count} 篇等待整理。关闭后它们将立即开始处理，可能使用高价时段。继续吗？`,
    )
  ) {
    target.checked = true
    return
  }
  save.mutate({ enabled: nextEnabled, windows: windows.value.map((item) => ({ ...item })) })
}

/** 新增独立每日窗口，默认值仅作为未启用的可编辑草稿。 */
function addWindow(): void {
  windows.value.push({ start: '00:00', end: '08:00' })
}

function removeWindow(index: number): void {
  if (windows.value.length === 1) return
  windows.value.splice(index, 1)
}

function saveWindows(): void {
  save.mutate({ enabled: enabled.value, windows: windows.value.map((item) => ({ ...item })) })
}
</script>

<template>
  <section>
    <p class="eyebrow">AI Schedule</p>
    <h1>AI 整理设置</h1>
    <p class="page-intro">文章始终立即入库；这里只控制三阶段 AI 分析何时调用模型，正文翻译不受影响。</p>

    <div v-if="schedule.isPending.value" class="panel">正在加载整理设置…</div>
    <div v-else-if="schedule.isError.value" class="panel error-panel">
      {{ schedule.error.value?.message }}
    </div>
    <template v-else-if="schedule.data.value">
      <section class="schedule-master panel">
        <div>
          <h2>定时整理（低价时段模式）</h2>
          <p>{{ enabled ? '普通文章仅在下方时段调用模型。' : '当前为提交后立即分析。' }}</p>
        </div>
        <label class="switch-control">
          <input
            type="checkbox"
            :checked="enabled"
            :disabled="save.isPending.value"
            @change="toggleEnabled"
          />
          <span>{{ enabled ? '已开启' : '已关闭' }}</span>
        </label>
      </section>

      <div class="schedule-state panel">
        <strong>{{ schedule.data.value.currently_allowed ? '当前允许执行分析' : '当前正在等待低价时段' }}</strong>
        <span v-if="nextWindowText">下一时段：{{ nextWindowText }}</span>
        <span>普通等待任务：{{ schedule.data.value.scheduled_job_count }} 篇</span>
        <span>时区：北京时间（Asia/Shanghai）</span>
      </div>

      <form class="questionnaire" @submit.prevent="saveWindows">
        <fieldset :disabled="save.isPending.value">
          <legend>每日整理时段</legend>
          <p>支持多个窗口和跨午夜时段；开始时间包含、结束时间不包含。</p>
          <div v-for="(item, index) in windows" :key="index" class="schedule-window-row">
            <input v-model="item.start" type="time" required />
            <span>至</span>
            <input v-model="item.end" type="time" required />
            <span v-if="item.start > item.end" class="muted-text">次日</span>
            <button
              type="button"
              class="secondary-button"
              :disabled="windows.length === 1"
              @click="removeWindow(index)"
            >
              移除
            </button>
          </div>
          <button type="button" class="secondary-button" @click="addWindow">添加时段</button>
        </fieldset>

        <div class="form-actions">
          <button class="primary-button" type="submit" :disabled="save.isPending.value">
            {{ save.isPending.value ? '正在保存…' : '保存时段' }}
          </button>
          <span v-if="save.isSuccess.value" class="success-text">整理设置已保存。</span>
          <span v-if="save.isError.value" class="error-text">{{ save.error.value?.message }}</span>
        </div>
      </form>
    </template>
  </section>
</template>
