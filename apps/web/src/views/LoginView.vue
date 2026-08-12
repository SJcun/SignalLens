<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { login } from '../api'
import { setAccessToken } from '../auth'

const route = useRoute()
const router = useRouter()
const username = ref('admin')
const password = ref('')
const busy = ref(false)
const error = ref('')

/** 登录成功后，初始账号优先进入改密页面。 */
async function submit(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    const result = await login(username.value.trim(), password.value)
    setAccessToken(result.access_token)
    const requested = typeof route.query.redirect === 'string' ? route.query.redirect : '/inbox'
    const safeRedirect = requested.startsWith('/') && !requested.startsWith('//') ? requested : '/inbox'
    await router.replace(result.must_change_password ? '/account' : safeRedirect)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '登录失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-card">
      <div class="brand-mark auth-brand">S</div>
      <p class="eyebrow">SIGNALLENS</p>
      <h1>登录阅读空间</h1>
      <p class="muted">Web 与浏览器插件使用同一个管理员账户。</p>
      <p v-if="route.query.changed" class="success-text">密码已修改，请使用新密码登录。</p>
      <form class="auth-form" @submit.prevent="submit">
        <label>
          用户名
          <input v-model="username" autocomplete="username" required />
        </label>
        <label>
          密码
          <input v-model="password" type="password" autocomplete="current-password" required autofocus />
        </label>
        <p v-if="error" class="form-error">{{ error }}</p>
        <button class="primary-button" type="submit" :disabled="busy">
          {{ busy ? '正在登录…' : '登录' }}
        </button>
      </form>
    </section>
  </main>
</template>
