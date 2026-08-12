import { API_BASE_URL } from '../shared/config'
import type { SignalLensCapture } from '../shared/capture'

interface SubmitMessage {
  type: 'SUBMIT_CAPTURE'
  payload: SignalLensCapture
}

interface SubmitResponse {
  ok: boolean
  error?: string
  contentId?: string
  analysisId?: string
  detailUrl?: string
}

/** 解析后端错误，避免 Popup 只显示模糊状态码。 */
async function responseError(response: Response): Promise<string> {
  try {
    const body = await response.json() as { detail?: string }
    return body.detail || `请求失败（${response.status}）`
  } catch {
    return `请求失败（${response.status}）`
  }
}

/** 由后台进程提交正文，Popup 关闭后网络请求仍可继续完成。 */
async function submitCapture(payload: SignalLensCapture): Promise<SubmitResponse> {
  const response = await fetch(`${API_BASE_URL}/captures`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
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

chrome.runtime.onMessage.addListener((message: SubmitMessage, _sender, sendResponse) => {
  if (message.type !== 'SUBMIT_CAPTURE') return false
  void submitCapture(message.payload)
    .then(sendResponse)
    .catch((error: Error) => sendResponse({ ok: false, error: error.message }))
  return true
})

