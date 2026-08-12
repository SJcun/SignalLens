<script setup lang="ts">
/** 应用外壳只负责全局导航，具体业务状态留在各页面。 */
const navigation = [
  { to: '/inbox', label: 'Inbox' },
  { to: '/preferences', label: '阅读偏好' },
  { to: '/stats', label: '统计' },
]
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <RouterLink class="brand" to="/inbox">
        <span class="brand-mark">S</span>
        <span>
          <strong>SignalLens</strong>
          <small>减少噪音，不减少边界</small>
        </span>
      </RouterLink>
      <nav aria-label="主导航">
        <RouterLink v-for="item in navigation" :key="item.to" :to="item.to">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="main-content">
      <RouterView />
    </main>
  </div>
</template>

