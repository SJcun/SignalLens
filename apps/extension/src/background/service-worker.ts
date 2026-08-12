import { API_BASE_URL } from '../shared/config'
import type { SignalLensCapture } from '../shared/capture'

interface SubmitMessage {
  type: 'SUBMIT_CAPTURE'
  payload: SignalLensCapture
}

interface SaveApiKeyMessage {
  type: 'SAVE_API_KEY'
  apiKey: string
}

interface ApiKeyStatusMessage {
  type: 'API_KEY_STATUS'
}

interface ClearApiKeyMessage {
  type: 'CLEAR_API_KEY'
}

type BackgroundMessage =
  | SubmitMessage
  | SaveApiKeyMessage
  | ApiKeyStatusMessage
  | ClearApiKeyMessage

interface SubmitResponse {
  ok: boolean
  error?: string
  keyRequired?: boolean
  contentId?: string
  analysisId?: string
  detailUrl?: string
}

const API_KEY_STORAGE_KEY = 'signalLensPluginApiKey'

/** 解析后端错误，避免 Popup 只显示模糊状态码。 */
async function responseError(response: Response): Promise<string> {
  try {
    const body = await response.json() as { detail?: string }
    return body.detail || `请求失败（${response.status}）`
  } catch {
    return `请求失败（${response.status}）`
  }
}

/** 从扩展专属存储读取插件 Key，页面脚本无法访问该值。 */
async function getApiKey(): Promise<string | null> {
  const stored = await chrome.storage.local.get(API_KEY_STORAGE_KEY)
  return (stored[API_KEY_STORAGE_KEY] as string | undefined) || null
}

/** 保存 Web 账户页生成的 Key；这里只校验固定格式，真实性在提交时由后端判断。 */
async function saveApiKey(apiKey: string): Promise<{ ok: boolean; error?: string }> {
  const normalized = apiKey.trim()
  if (!/^sk-sl-[A-Za-z0-9_-]{32,}$/.test(normalized)) {
    return { ok: false, error: 'Key 格式不正确，应以 sk-sl- 开头' }
  }
  await chrome.storage.local.set({ [API_KEY_STORAGE_KEY]: normalized })
  return { ok: true }
}

/** 返回非敏感配置状态，不把完整 Key 传回 Popup。 */
async function apiKeyStatus(): Promise<{
  ok: boolean
  configured: boolean
  keyPrefix?: string
}> {
  const apiKey = await getApiKey()
  return {
    ok: true,
    configured: Boolean(apiKey),
    keyPrefix: apiKey ? apiKey.slice(0, 14) : undefined,
  }
}

/** 清除插件本地 Key；后端 Key 是否撤销由 Web 账户页控制。 */
async function clearApiKey(): Promise<{ ok: boolean }> {
  await chrome.storage.local.remove(API_KEY_STORAGE_KEY)
  return { ok: true }
}

/** 由后台进程携带最小权限 Key 提交正文，Popup 关闭后请求仍可完成。 */
async function submitCapture(payload: SignalLensCapture): Promise<SubmitResponse> {
  const apiKey = await getApiKey()
  if (!apiKey) return { ok: false, error: '请先填写插件 Key', keyRequired: true }
  const response = await fetch(`${API_BASE_URL}/captures`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify(payload),
  })
  if (response.status === 401) {
    await chrome.storage.local.remove(API_KEY_STORAGE_KEY)
    return { ok: false, error: '插件 Key 无效或已被替换，请重新填写', keyRequired: true }
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
  else if (message.type === 'SAVE_API_KEY') operation = saveApiKey(message.apiKey)
  else if (message.type === 'API_KEY_STATUS') operation = apiKeyStatus()
  else if (message.type === 'CLEAR_API_KEY') operation = clearApiKey()
  else return false
  void operation
    .then(sendResponse)
    .catch((error: Error) => sendResponse({ ok: false, error: error.message }))
  return true
})
