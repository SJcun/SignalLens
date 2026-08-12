/**
 * content script 入口（替代原 content/extract.js）：
 * 重建干净 document → 规范化 → 编排提取 → Front Matter → sendMessage。
 * 打包产物：dist/content.js，由 popup 通过 chrome.scripting.executeScript 注入，
 * 注入顺序：lib/Readability.js → lib/turndown.js → dist/content.js。
 */
import { extractPage } from '../extraction/orchestrator';
import { buildCleanDoc } from './build-document';
import { registerBuiltinAdapters } from '../adapters/sites';
import { matchAdapter } from '../adapters';
import { absolutize } from '../normalize/links';
import { makeTurndown } from '../markdown/turndown-service';
import { buildFrontMatter } from '../markdown/frontmatter';
import { computeQuality } from '../extraction/quality-gate';
import { mergeMetadata } from '../metadata/metadata-merger';
import {
  isReusableExtractionResult,
  waitForAdapterContent,
  type CachedExtractionResult,
} from './readiness';

;(async () => {
  'use strict';

  // 注册内置站点适配器（幂等）
  registerBuiltinAdapters();

  // 注入代码版本：升级后同页面的旧缓存应失效（否则重载扩展后仍返回旧结果）
  const MD_VERSION = 'v7';

  // 幂等保护：仅复用同版本、同 URL 的 good 结果；warning/poor 允许正文就绪后重试。
  const cached = window.__MD_EXTRACT_RESULT__ as CachedExtractionResult | undefined;
  if (
    window.__MD_EXTRACT_RAN__ &&
    window.__MD_VERSION__ === MD_VERSION &&
    isReusableExtractionResult(cached, window.__MD_EXTRACT_URL__, location.href)
  ) {
    chrome.runtime.sendMessage({ type: 'MD_RESULT', result: cached });
    return;
  }

  const send = (result: unknown): void => {
    window.__MD_EXTRACT_RESULT__ = result;
    window.__MD_EXTRACT_RAN__ = true;
    window.__MD_VERSION__ = MD_VERSION;
    window.__MD_EXTRACT_URL__ = location.href;
    try {
      chrome.runtime.sendMessage({ type: 'MD_RESULT', result });
    } catch {
      // popup 已关闭等情况：结果已缓存在 window 上
    }
  };

  /** 手动选择模式：overlay 覆盖页面，hover 高亮候选，点击提取该元素，Esc 取消 */
  const startManualSelect = (sendResult: (r: unknown) => void): void => {
    const overlay = document.createElement('div');
    overlay.style.cssText =
      'position:fixed;inset:0;z-index:2147483646;background:rgba(0,0,0,0.12);cursor:crosshair;';
    const highlight = document.createElement('div');
    highlight.style.cssText =
      'position:fixed;z-index:2147483647;pointer-events:none;outline:2px solid #1a73e8;' +
      'background:rgba(26,115,232,0.10);display:none;';
    const hint = document.createElement('div');
    hint.style.cssText =
      'position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:2147483647;' +
      'background:rgba(17,17,17,0.92);color:#fff;padding:6px 16px;border-radius:6px;' +
      'font:12px/1.5 system-ui,sans-serif;pointer-events:none;box-shadow:0 2px 8px rgba(0,0,0,0.3);';
    hint.textContent = '点击选择正文区域（Esc 取消）';

    let current: Element | null = null;
    let done = false;

    const cleanup = (): void => {
      if (done) return;
      done = true;
      overlay.remove();
      highlight.remove();
      hint.remove();
      document.removeEventListener('mousemove', onMove, true);
      document.removeEventListener('click', onClick, true);
      document.removeEventListener('keydown', onKey, true);
    };

    const onMove = (e: MouseEvent): void => {
      const el = (e.target as Element | null)?.closest?.(
        'article, main, section, [role="main"], p, div, h1, h2, h3, blockquote'
      ) as Element | null;
      if (!el || done) {
        current = null;
        highlight.style.display = 'none';
        return;
      }
      current = el;
      const rect = el.getBoundingClientRect();
      highlight.style.display = 'block';
      highlight.style.left = rect.left + 'px';
      highlight.style.top = rect.top + 'px';
      highlight.style.width = rect.width + 'px';
      highlight.style.height = rect.height + 'px';
    };

    const onClick = (e: MouseEvent): void => {
      e.preventDefault();
      e.stopPropagation();
      cleanup();
      if (!current) {
        sendResult({ ok: false, error: '未选择到有效区域，请重新选择' });
        return;
      }
      try {
        const holder = document.createElement('div');
        holder.appendChild(current.cloneNode(true));
        absolutize(holder, document.baseURI || location.href);
        const md = makeTurndown().turndown(holder.innerHTML);
        if (!md.trim()) {
          sendResult({ ok: false, error: '所选区域无可转换内容' });
          return;
        }
        const metadata = mergeMetadata({}, document, location.href);
        const charCount = md.replace(/\s/g, '').length;
        const paragraphs = md.split(/\n\s*\n/).filter((p) => p.trim()).length;
        const quality = computeQuality(md, { charCount, paragraphs });
        sendResult({
          ok: true,
          error: undefined,
          title: metadata.title,
          author: metadata.author,
          publishedAt: metadata.publishedAt,
          capturedAt: metadata.capturedAt,
          source: metadata.source,
          charCount,
          paragraphs,
          md: buildFrontMatter(metadata, quality, 'manual') + md,
          fallback: true,
          engineId: 'manual',
          quality: quality.level,
          warnings: quality.warnings,
        });
      } catch (err) {
        sendResult({ ok: false, error: '提取失败：' + (err as Error).message });
      }
    };

    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') {
        cleanup();
        sendResult({ ok: false, error: '已取消手动选择' });
      }
    };

    document.body.appendChild(overlay);
    document.body.appendChild(highlight);
    document.body.appendChild(hint);
    document.addEventListener('mousemove', onMove, true);
    document.addEventListener('click', onClick, true);
    document.addEventListener('keydown', onKey, true);
  };

  if (typeof Readability === 'undefined' || typeof TurndownService === 'undefined') {
    send({ ok: false, error: '依赖库注入失败（Readability/Turndown 未就绪）' });
    return;
  }

  // popup 通过 executeScript(func) 设置的标记（同一 isolated world 共享）
  const win = window as unknown as {
    __MD_FORCE_FULL_PAGE__?: boolean;
    __MD_SELECTION_MODE__?: boolean;
    __MD_MANUAL_SELECT__?: boolean;
  };

  // 手动选择模式：不立即提取，等待用户点击页面元素
  if (win.__MD_MANUAL_SELECT__) {
    win.__MD_MANUAL_SELECT__ = undefined;
    startManualSelect(send);
    return;
  }

  const forceFullPage = !!win.__MD_FORCE_FULL_PAGE__;
  win.__MD_FORCE_FULL_PAGE__ = undefined;
  const useSelection = !!win.__MD_SELECTION_MODE__;
  win.__MD_SELECTION_MODE__ = undefined;

  // 动态页面等待：容器出现不代表正文已经写入，须等到内容达到适配器可用阈值。
  const adapter = matchAdapter(location.href);
  if (adapter?.preferredContentSelector?.length && !useSelection && !forceFullPage) {
    await waitForAdapterContent(document, adapter.preferredContentSelector);
  }

  let newDoc: Document;
  try {
    newDoc = buildCleanDoc(document);
  } catch (e) {
    send({ ok: false, error: '页面文档重建失败：' + (e as Error).message });
    return;
  }

  const r = extractPage({ document: newDoc, url: location.href, forceFullPage, useSelection });
  send({
    ok: r.ok,
    error: r.error,
    title: r.metadata.title,
    author: r.metadata.author,
    publishedAt: r.metadata.publishedAt,
    capturedAt: r.metadata.capturedAt,
    source: r.metadata.source,
    charCount: r.charCount,
    paragraphs: r.paragraphs,
    md: r.markdown,
    fallback: r.fallback,
    engineId: r.engineId,
    quality: r.quality.level,
    warnings: r.quality.warnings,
  });
})();
