/**
 * 独立预览页（阶段 4）：长文 Markdown 渲染预览 + 源码查看 + 元数据/警告 + 复制下载。
 * 数据来源：popup 存入 chrome.storage.local 的 mdPreview。
 * 打包产物：dist/preview.js。
 */
'use strict';

import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { buildExportJson, type QualityLevel } from '../shared/export';

interface PreviewData {
  title: string;
  source: string;
  charCount: number;
  paragraphs: number;
  engineId?: string;
  quality?: string;
  warnings?: string[];
  md: string;
}

const $ = <T extends HTMLElement = HTMLElement>(id: string): T =>
  document.getElementById(id) as T;

const el = {
  title: $('title'),
  meta: $('meta'),
  quality: $('quality'),
  engine: $('engine'),
  warnings: $('warnings'),
  rendered: $('rendered'),
  source: $<HTMLPreElement>('source'),
  copy: $<HTMLButtonElement>('copy'),
  download: $<HTMLButtonElement>('download'),
  downloadJson: $<HTMLButtonElement>('download-json'),
  tabRendered: $<HTMLButtonElement>('tab-rendered'),
  tabSource: $<HTMLButtonElement>('tab-source'),
};

const QUALITY_TEXT: Record<string, string> = {
  good: '质量：可信',
  warning: '质量：有疑点',
  poor: '质量：较差',
  failed: '质量：失败',
};

let data: PreviewData | null = null;

function sanitizeFilename(name: string): string {
  return (
    name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').replace(/\s+/g, ' ').trim().slice(0, 80) ||
    '未命名文章'
  );
}

function render(data: PreviewData): void {
  el.title.textContent = data.title || '未命名文章';
  el.meta.textContent = `${data.source} · ${data.charCount.toLocaleString()} 字符 · ${data.paragraphs} 段`;
  if (data.engineId) {
    el.engine.textContent = '提取方式：' + data.engineId;
    el.engine.classList.remove('hidden');
  }
  if (data.quality) {
    el.quality.textContent = QUALITY_TEXT[data.quality] || data.quality;
    el.quality.className = 'quality ' + data.quality;
    el.quality.classList.remove('hidden');
  }
  if (data.warnings && data.warnings.length) {
    el.warnings.innerHTML = '';
    for (const w of data.warnings) {
      const li = document.createElement('li');
      li.textContent = '⚠ ' + w;
      el.warnings.appendChild(li);
    }
    el.warnings.classList.remove('hidden');
  }

  // 渲染预览：marked → DOMPurify 清理（安全要求）
  try {
    el.rendered.innerHTML = DOMPurify.sanitize(marked.parse(data.md, { async: false }) as string);
  } catch {
    el.rendered.textContent = data.md;
  }
  // 源码视图
  el.source.textContent = data.md;
}

function switchTab(which: 'rendered' | 'source'): void {
  const isRendered = which === 'rendered';
  el.rendered.classList.toggle('active', isRendered);
  el.source.classList.toggle('active', !isRendered);
  el.tabRendered.classList.toggle('active', isRendered);
  el.tabSource.classList.toggle('active', !isRendered);
}

el.tabRendered.addEventListener('click', () => switchTab('rendered'));
el.tabSource.addEventListener('click', () => switchTab('source'));

el.copy.addEventListener('click', async () => {
  if (!data) return;
  try {
    await navigator.clipboard.writeText(data.md);
    el.copy.textContent = '已复制 ✓';
    setTimeout(() => (el.copy.textContent = '复制 Markdown'), 1200);
  } catch {
    el.copy.textContent = '复制失败';
  }
});

el.download.addEventListener('click', () => {
  if (!data) return;
  const url = 'data:text/markdown;charset=utf-8,' + encodeURIComponent(data.md);
  void chrome.downloads.download({ url, filename: sanitizeFilename(data.title) + '.md', saveAs: false });
});

const extractCapturedAt = (md: string): string | undefined => {
  const m = md.match(/^captured_at:\s*"([^"]+)"/m);
  return m ? m[1] : undefined;
};

el.downloadJson.addEventListener('click', () => {
  if (!data) return;
  const codeBlocks = Math.floor((data.md.match(/```/g) || []).length / 2);
  const json = buildExportJson({
    metadata: { title: data.title, source: data.source, capturedAt: extractCapturedAt(data.md) },
    markdown: data.md,
    quality: { level: (data.quality || 'unknown') as QualityLevel, warnings: data.warnings || [] },
    extraction: { engine: data.engineId || 'unknown' },
    metrics: { codeBlocks, tables: 0 },
  });
  const url = 'data:application/json;charset=utf-8,' + encodeURIComponent(json);
  void chrome.downloads.download({
    url,
    filename: sanitizeFilename(data.title) + '.analysis.json',
    saveAs: false,
  });
});

chrome.storage.local.get(['mdPreview']).then((result: { mdPreview?: PreviewData }) => {
  const mdPreview = result.mdPreview;
  if (!mdPreview || !mdPreview.md) {
    el.title.textContent = '没有可预览的内容';
    el.meta.textContent = '请先在插件 popup 中转换一篇文章，再打开预览。';
    return;
  }
  data = mdPreview;
  render(data);
});
