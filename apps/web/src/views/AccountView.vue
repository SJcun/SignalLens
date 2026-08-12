<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { changePassword, getCurrentUser, logout } from '../api'

const router = useRouter()
const account = useQuery({ queryKey: ['current-user'], queryFn: getCurrentUser })
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const busy = ref(false)
const error = ref('')

/** 校验两次输入后修改密码；服务端成功时所有设备需要重新登录。 */
async function submitPassword(): Promise<void> {
  error.value = ''
  if (newPassword.value !== confirmPassword.value) {
    error.value = '两次输入的新密码不一致'
    return
  }
  busy.value = true
  try {
    await changePassword(currentPassword.value, newPassword.value)
    await router.replace({ path: '/login', query: { changed: '1' } })
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '密码修改失败'
  } finally {
    busy.value = false
  }
}

/** 主动撤销当前浏览器会话。 */
async function signOut(): Promise<void> {
  await logout()
  await router.replace('/login')
}
</script>

<template>
  <section class="page narrow-page">
    <p class="eyebrow">ACCOUNT SECURITY</p>
    <h1>账户安全</h1>
    <p class="page-intro">当前账户：{{ account.data.value?.username || 'admin' }}</p>

    <div v-if="account.data.value?.must_change_password" class="warning-banner">
      当前仍在使用系统生成的初始密码，请立即修改。
    </div>

    <form class="panel settings-form" @submit.prevent="submitPassword">
      <h2>修改密码</h2>
      <label>
        当前密码
        <input v-model="currentPassword" type="password" autocomplete="current-password" required />
      </label>
      <label>
        新密码
        <input v-model="newPassword" type="password" autocomplete="new-password" minlength="12" required />
        <small>至少 12 个字符，建议使用密码管理器生成。</small>
      </label>
      <label>
        再次输入新密码
        <input v-model="confirmPassword" type="password" autocomplete="new-password" minlength="12" required />
      </label>
      <p v-if="error" class="form-error">{{ error }}</p>
      <button class="primary-button" type="submit" :disabled="busy">
        {{ busy ? '正在修改…' : '修改密码并重新登录' }}
      </button>
    </form>

    <button class="secondary-button account-logout" type="button" @click="signOut">退出当前登录</button>
  </section>
</template>
