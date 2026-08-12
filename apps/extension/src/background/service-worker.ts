import { API_BASE_URL } from '../shared/config'
import type { SignalLensCapture } from '../shared/capture'

interface SubmitMessage {
  type: 'SUBMIT_CAPTURE'
  payload: SignalLensCapture
}

interface SubmitResponse {
  ok: boolean
  error?: string
  authRequired?: boolean
  contentId?: string
  analysisId?: string
  detailUrl?: string
}

interface LoginMessage {
  type: 'LOGIN'
  username: string
  password: string
}

interface AuthStatusMessage {
  type: 'AUTH_STATUS'
}

interface LogoutMessage {
  type: 'LOGOUT'
}

type BackgroundMessage = SubmitMessage | LoginMessage | AuthStatusMessage | LogoutMessage

interface StoredAuth {
  accessToken: string
  username: string
  mustChangePassword: boolean
  expiresAt: string
}

const AUTH_STORAGE_KEY = 'signalLensAuth'

/** 解析后端错误，避免 Popup 只显示模糊状态码。 */
async function responseError(response: Response): Promise<string> {
  try {
    const body = await response.json() as { detail?: string }
    return body.detail || `请求失败（${response.status}）`
  } catch {
    return `请求失败（${response.status}）`
  }
}

/** 从扩展专属存储读取会话，页面脚本无法访问该令牌。 */
async function getStoredAuth(): Promise<StoredAuth | null> {
  const stored = await chrome.storage.local.get(AUTH_STORAGE_KEY)
  return (stored[AUTH_STORAGE_KEY] as StoredAuth | undefined) || null
}

/** 使用与 Web 相同的管理员账号登录插件。 */
async function login(username: string, password: string): Promise<{
  ok: boolean
  error?: string
  username?: string
  mustChangePassword?: boolean
}> {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!response.ok) return { ok: false, error: await responseError(response) }
  const result = await response.json() as {
    access_token: string
    username: string
    must_change_password: boolean
    expires_at: string
  }
  const auth: StoredAuth = {
    accessToken: result.access_token,
    username: result.username,
    mustChangePassword: result.must_change_password,
    expiresAt: result.expires_at,
  }
  await chrome.storage.local.set({ [AUTH_STORAGE_KEY]: auth })
  return {
    ok: true,
    username: auth.username,
    mustChangePassword: auth.mustChangePassword,
  }
}

/** 向后端确认本地令牌仍有效；失效令牌会立即移除。 */
async function authStatus(): Promise<{
  ok: boolean
  authenticated: boolean
  error?: string
  username?: string
  mustChangePassword?: boolean
}> {
  const auth = await getStoredAuth()
  if (!auth) return { ok: true, authenticated: false }
  const response = await fetch(`${API_BASE_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${auth.accessToken}` },
  })
  if (response.status === 401) {
    await chrome.storage.local.remove(AUTH_STORAGE_KEY)
    return { ok: true, authenticated: false }
  }
  if (!response.ok) {
    return { ok: false, authenticated: false, error: await responseError(response) }
  }
  const current = await response.json() as {
    username: string
    must_change_password: boolean
  }
  return {
    ok: true,
    authenticated: true,
    username: current.username,
    mustChangePassword: current.must_change_password,
  }
}

/** 撤销当前插件会话；后端不可用时也清除本地令牌。 */
async function logout(): Promise<{ ok: boolean }> {
  const auth = await getStoredAuth()
  try {
    if (auth) {
      await fetch(`${API_BASE_URL}/auth/logout`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${auth.accessToken}` },
      })
    }
  } finally {
    await chrome.storage.local.remove(AUTH_STORAGE_KEY)
  }
  return { ok: true }
}

/** 由后台进程提交正文，Popup 关闭后网络请求仍可继续完成。 */
async function submitCapture(payload: SignalLensCapture): Promise<SubmitResponse> {
  const auth = await getStoredAuth()
  if (!auth) return { ok: false, error: '请先登录插件', authRequired: true }
  const response = await fetch(`${API_BASE_URL}/captures`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${auth.accessToken}`,
    },
    body: JSON.stringify(payload),
  })
  if (response.status === 401) {
    await chrome.storage.local.remove(AUTH_STORAGE_KEY)
    return { ok: false, error: '登录已过期，请重新登录', authRequired: true }
  }
  if (!response.ok) return { ok: false, error: await responseError(response) }
  const result = await response.json() as {
    content_id: string
    analysis_id: string
    detail_url: string
  }
  await chrome.storage.local.set({
    lastSignalLensSubmission: {
      contentId: result.content_id,
      analysisId: result.analysis_id,
      createdAt: new Date().toISOString(),
    },
  })
  return {
    ok: true,
    contentId: result.content_id,
    analysisId: result.analysis_id,
    detailUrl: result.detail_url,
  }
}

chrome.runtime.onMessage.addListener((message: BackgroundMessage, _sender, sendResponse) => {
  let operation
  if (message.type === 'SUBMIT_CAPTURE') operation = submitCapture(message.payload)
  else if (message.type === 'LOGIN') operation = login(message.username, message.password)
  else if (message.type === 'AUTH_STATUS') operation = authStatus()
  else if (message.type === 'LOGOUT') operation = logout()
  else return false
  void operation
    .then(sendResponse)
    .catch((error: Error) => sendResponse({ ok: false, error: error.message }))
  return true
})
