<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  changePassword,
  generatePluginKey,
  getCurrentUser,
  getPluginKeyStatus,
  logout,
  revokePluginKey,
} from '../api'

const router = useRouter()
const account = useQuery({ queryKey: ['current-user'], queryFn: getCurrentUser })
const pluginKey = useQuery({ queryKey: ['plugin-key'], queryFn: getPluginKeyStatus })
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const busy = ref(false)
const error = ref('')
const generatedKey = ref('')
const pluginKeyBusy = ref(false)
const pluginKeyError = ref('')
const copied = ref(false)

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

/** 生成新的插件 Key；已有 Key 时明确提示旧值将立即失效。 */
async function createPluginKey(): Promise<void> {
  if (pluginKey.data.value?.configured && !window.confirm('重新生成后，插件中原来的 Key 会立即失效。继续吗？')) return
  pluginKeyBusy.value = true
  pluginKeyError.value = ''
  try {
    const result = await generatePluginKey()
    generatedKey.value = result.api_key
    copied.value = false
    await pluginKey.refetch()
  } catch (reason) {
    pluginKeyError.value = reason instanceof Error ? reason.message : '插件 Key 生成失败'
  } finally {
    pluginKeyBusy.value = false
  }
}

/** 复制仅展示一次的完整 Key。 */
async function copyPluginKey(): Promise<void> {
  try {
    await navigator.clipboard.writeText(generatedKey.value)
    copied.value = true
  } catch {
    pluginKeyError.value = '自动复制失败，请手动复制 Key'
  }
}

/** 撤销当前 Key，阻止所有已配置插件继续提交。 */
async function removePluginKey(): Promise<void> {
  if (!window.confirm('撤销后，插件将无法继续提交文档。继续吗？')) return
  pluginKeyBusy.value = true
  pluginKeyError.value = ''
  try {
    await revokePluginKey()
    generatedKey.value = ''
    await pluginKey.refetch()
  } catch (reason) {
    pluginKeyError.value = reason instanceof Error ? reason.message : '插件 Key 撤销失败'
  } finally {
    pluginKeyBusy.value = false
  }
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

    <section class="panel settings-form plugin-key-panel">
      <div>
        <h2>浏览器插件 Key</h2>
        <p>插件无需登录。把这里生成的 Key 填入插件后，只能提交文档，不能读取账户数据。</p>
      </div>

      <div v-if="pluginKey.data.value?.configured" class="key-status-row">
        <span>当前 Key：<code>{{ pluginKey.data.value.key_prefix }}••••••</code></span>
        <span v-if="pluginKey.data.value.last_used_at">插件已成功使用</span>
      </div>
      <p v-else class="muted">尚未生成插件 Key。</p>

      <div v-if="generatedKey" class="generated-key">
        <strong>请立即复制，此完整 Key 只显示一次</strong>
        <div class="key-copy-row">
          <input :value="generatedKey" readonly aria-label="新生成的插件 Key" />
          <button class="secondary-button" type="button" @click="copyPluginKey">
            {{ copied ? '已复制' : '复制' }}
          </button>
        </div>
      </div>

      <p v-if="pluginKeyError" class="form-error">{{ pluginKeyError }}</p>
      <div class="form-actions">
        <button class="primary-button" type="button" :disabled="pluginKeyBusy" @click="createPluginKey">
          {{ pluginKey.data.value?.configured ? '重新生成 Key' : '生成插件 Key' }}
        </button>
        <button
          v-if="pluginKey.data.value?.configured"
          class="secondary-button"
          type="button"
          :disabled="pluginKeyBusy"
          @click="removePluginKey"
        >
          撤销 Key
        </button>
      </div>
    </section>

    <button class="secondary-button account-logout" type="button" @click="signOut">退出当前登录</button>
  </section>
</template>
