import { buildCapture } from '../shared/capture'
import { buildExportJson, type QualityLevel } from '../shared/export'

interface PopupResult {
  ok: boolean
  error?: string
  title?: string
  author?: string
  publishedAt?: string
  capturedAt?: string
  source?: string
  charCount?: number
  paragraphs?: number
  md?: string
  fallback?: boolean
  engineId?: string
  quality?: string
  warnings?: string[]
}

interface PopupState {
  md: string
  title: string
  source: string
  author?: string
  publishedAt?: string
  capturedAt?: string
  charCount: number
  paragraphs: number
  engineId: string
  quality: QualityLevel
  warnings: string[]
  captureId: string
  busy: boolean
}

const state: PopupState = {
  md: '',
  title: '未命名文章',
  source: '',
  charCount: 0,
  paragraphs: 0,
  engineId: 'unknown',
  quality: 'warning',
  warnings: [],
  captureId: crypto.randomUUID(),
  busy: false,
}

const $ = <T extends HTMLElement = HTMLElement>(id: string): T => document.getElementById(id) as T
const el = {
  status: $('status'),
  meta: $('meta'),
  metaTitle: $('meta-title'),
  metaCount: $('meta-count'),
  quality: $('quality'),
  preview: $<HTMLPreElement>('preview'),
  actions: $('actions'),
  copy: $<HTMLButtonElement>('copy'),
  download: $<HTMLButtonElement>('download'),
  downloadJson: $<HTMLButtonElement>('download-json'),
  openPreview: $<HTMLButtonElement>('open-preview'),
  reconvert: $<HTMLButtonElement>('reconvert'),
  fullpage: $<HTMLButtonElement>('fullpage'),
  selection: $<HTMLButtonElement>('selection'),
  manual: $<HTMLButtonElement>('manual'),
  analyze: $<HTMLButtonElement>('analyze'),
  analysisResult: $('analysis-result'),
  analysisDetail: $<HTMLAnchorElement>('analysis-detail'),
}

const QUALITY_TEXT: Record<QualityLevel, string> = {
  good: '可信',
  warning: '有疑点',
  poor: '质量差',
  failed: '失败',
}

/** 将未知质量值收敛到后端可接受的枚举。 */
function normalizeQuality(value?: string): QualityLevel {
  return value === 'good' || value === 'poor' || value === 'failed' ? value : 'warning'
}

/** 显示提取或网络状态。 */
function setStatus(text: string, isError = false): void {
  el.status.textContent = text
  el.status.classList.toggle('error', isError)
  el.status.classList.remove('hidden')
}

/** 把内容脚本返回结果写入 Popup 状态与预览区。 */
function showResult(result: PopupResult): void {
  if (!result.ok) {
    setStatus(result.error || '转换失败', true)
    return
  }
  state.md = result.md || ''
  state.title = result.title || '未命名文章'
  state.author = result.author
  state.publishedAt = result.publishedAt
  state.capturedAt = result.capturedAt
  state.source = result.source || state.source
  state.charCount = result.charCount || 0
  state.paragraphs = result.paragraphs || 0
  state.engineId = result.engineId || 'unknown'
  state.quality = normalizeQuality(result.quality)
  state.warnings = result.warnings || []
  state.captureId = crypto.randomUUID()

  el.status.classList.add('hidden')
  el.metaTitle.textContent = state.title
  el.metaCount.textContent = `${state.charCount.toLocaleString()} 字符 · ${state.paragraphs} 段`
  el.quality.textContent = `质量：${QUALITY_TEXT[state.quality]}（${state.engineId}）`
  el.quality.className = `quality ${state.quality}`
  el.preview.textContent = state.md
  el.meta.classList.remove('hidden')
  el.preview.classList.remove('hidden')
  el.actions.classList.remove('hidden')
  el.analysisResult.classList.add('hidden')
  el.analyze.disabled = state.quality === 'failed'
}

/** 在当前标签页执行对应的 PageSift 提取模式。 */
async function convert(mode: 'auto' | 'fullpage' | 'selection' | 'manual' = 'auto'): Promise<void> {
  if (state.busy) return
  state.busy = true
  el.actions.classList.add('hidden')
  el.meta.classList.add('hidden')
  el.preview.classList.add('hidden')
  setStatus(mode === 'manual' ? '请在页面中点击正文区域…' : '正在提取当前网页…')

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab.id || !tab.url || !/^(https?|file):/.test(tab.url)) {
    state.busy = false
    setStatus('当前页面不支持提取，请打开普通网页后重试。', true)
    return
  }
  state.source = tab.url
  try {
    const flags: Record<string, boolean> = {
      ...(mode === 'fullpage' ? { __MD_FORCE_FULL_PAGE__: true } : {}),
      ...(mode === 'selection' ? { __MD_SELECTION_MODE__: true } : {}),
      ...(mode === 'manual' ? { __MD_MANUAL_SELECT__: true } : {}),
    }
    if (Object.keys(flags).length) {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (values) => Object.assign(window, values),
        args: [flags],
      })
    }
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['lib/Readability.js', 'lib/turndown.js', 'dist/content.js'],
    })
  } catch (error) {
    state.busy = false
    setStatus(`注入失败：${(error as Error).message}`, true)
  }
}

chrome.runtime.onMessage.addListener((message: { type?: string; result?: PopupResult }) => {
  if (message.type === 'MD_RESULT' && message.result) {
    state.busy = false
    showResult(message.result)
  }
})

/** 把当前正文提交到唯一 SignalLens 后端。 */
async function submitAnalysis(): Promise<void> {
  if (!state.md || state.quality === 'failed') return
  if (state.quality === 'poor' && !window.confirm('正文提取质量较差，仍要提交分析吗？')) return
  el.analyze.disabled = true
  setStatus('正在提交到 SignalLens…')
  const response = await chrome.runtime.sendMessage({
    type: 'SUBMIT_CAPTURE',
    payload: buildCapture({
      captureId: state.captureId,
      title: state.title,
      author: state.author,
      source: state.source,
      markdown: state.md,
      quality: state.quality,
      warnings: state.warnings,
      engine: state.engineId,
    }),
  }) as { ok: boolean; error?: string; contentId?: string }
  el.analyze.disabled = false
  if (!response.ok) {
    setStatus(response.error || '提交失败', true)
    return
  }
  el.status.classList.add('hidden')
  el.analysisResult.classList.remove('hidden')
  el.analysisDetail.href = `https://lens.example.com/contents/${response.contentId}`
}

/** 下载当前 Markdown 正文。 */
function downloadMarkdown(): void {
  const filename = `${sanitizeFilename(state.title)}.md`
  const url = `data:text/markdown;charset=utf-8,${encodeURIComponent(state.md)}`
  void chrome.downloads.download({ url, filename, saveAs: false })
}

/** 下载与 PageSift 兼容的结构化提取结果。 */
function downloadJson(): void {
  const json = buildExportJson({
    metadata: {
      title: state.title,
      author: state.author,
      source: state.source,
      publishedAt: state.publishedAt,
      capturedAt: state.capturedAt,
    },
    markdown: state.md,
    quality: { level: state.quality, warnings: state.warnings },
    extraction: { engine: state.engineId },
    metrics: {
      codeBlocks: Math.floor((state.md.match(/```/g) || []).length / 2),
      tables: state.md.split('\n').filter((line) => /^\|/.test(line)).length,
    },
  })
  const url = `data:application/json;charset=utf-8,${encodeURIComponent(json)}`
  void chrome.downloads.download({ url, filename: `${sanitizeFilename(state.title)}.json` })
}

/** 清理操作系统不允许出现在文件名中的字符。 */
function sanitizeFilename(value: string): string {
  return value.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').trim().slice(0, 80) || '未命名文章'
}

/** 复制 Markdown，失败时选中预览供用户手动复制。 */
async function copyMarkdown(): Promise<void> {
  try {
    await navigator.clipboard.writeText(state.md)
    el.copy.textContent = '已复制 ✓'
    setTimeout(() => { el.copy.textContent = '复制 Markdown' }, 1200)
  } catch {
    const range = document.createRange()
    range.selectNodeContents(el.preview)
    window.getSelection()?.addRange(range)
    setStatus('自动复制失败，内容已选中，请按 Ctrl+C。', true)
  }
}

/** 将正文放入独立预览页使用的本地存储。 */
async function openPreview(): Promise<void> {
  await chrome.storage.local.set({ mdPreview: { ...state, md: state.md } })
  await chrome.tabs.create({ url: chrome.runtime.getURL('preview/preview.html') })
}

el.analyze.addEventListener('click', () => void submitAnalysis())
el.copy.addEventListener('click', () => void copyMarkdown())
el.download.addEventListener('click', downloadMarkdown)
el.downloadJson.addEventListener('click', downloadJson)
el.openPreview.addEventListener('click', () => void openPreview())
el.reconvert.addEventListener('click', () => void convert())
el.fullpage.addEventListener('click', () => void convert('fullpage'))
el.selection.addEventListener('click', () => void convert('selection'))
el.manual.addEventListener('click', () => void convert('manual'))

void convert()

