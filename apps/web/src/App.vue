<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import { initializeTheme, setTheme, type Theme } from './theme'

const route = useRoute()
const showApplicationShell = computed(() => !route.meta.public)
const theme = ref<Theme>(initializeTheme())
const themeToggleLabel = computed(() =>
  theme.value === 'dark' ? '切换到浅色模式' : '切换到深色模式',
)
const themeToggleIcon = computed(() => (theme.value === 'dark' ? '☀' : '☾'))

/** 应用外壳只负责登录后的全局导航，具体业务状态留在各页面。 */
const navigation = [
  { to: '/inbox', label: 'Inbox' },
  { to: '/preferences', label: '阅读偏好' },
  { to: '/user-state', label: '当前状态' },
  { to: '/memory', label: '认知记忆' },
  { to: '/analysis-schedule', label: '整理设置' },
  { to: '/stats', label: '统计' },
  { to: '/account', label: '账户' },
]

/** 内容详情属于 Inbox，进入文章后仍保留对应的主导航选中状态。 */
function isNavigationActive(target: string): boolean {
  if (target === '/inbox') {
    return route.path === '/inbox' || route.path.startsWith('/contents/')
  }
  return route.path === target
}

/** 在深色和浅色之间切换，并记住当前浏览器的选择。 */
function toggleTheme(): void {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  setTheme(theme.value)
}
</script>

<template>
  <div v-if="showApplicationShell" class="app-shell">
    <aside class="sidebar">
      <RouterLink class="brand" to="/inbox">
        <span class="brand-mark">S</span>
        <span>
          <strong>SignalLens</strong>
          <small>减少噪音，不减少边界</small>
        </span>
      </RouterLink>
      <nav aria-label="主导航">
        <RouterLink
          v-for="item in navigation"
          :key="item.to"
          :to="item.to"
          :class="{ 'router-link-active': isNavigationActive(item.to) }"
        >
          {{ item.label }}
        </RouterLink>
      </nav>
      <button
        class="theme-toggle"
        type="button"
        :aria-label="themeToggleLabel"
        :title="themeToggleLabel"
        @click="toggleTheme"
      >
        <span aria-hidden="true">{{ themeToggleIcon }}</span>
        {{ themeToggleLabel }}
      </button>
    </aside>
    <main class="main-content">
      <RouterView />
    </main>
  </div>
  <div v-else class="public-page-shell">
    <button
      class="theme-toggle public-theme-toggle"
      type="button"
      :aria-label="themeToggleLabel"
      :title="themeToggleLabel"
      @click="toggleTheme"
    >
      <span aria-hidden="true">{{ themeToggleIcon }}</span>
      {{ themeToggleLabel }}
    </button>
    <RouterView />
  </div>
</template>
