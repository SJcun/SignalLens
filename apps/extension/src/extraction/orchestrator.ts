/**
 * 提取编排器（阶段 3：分级执行，V2 §10.3）。
 *
 * 调用顺序：
 *   forceFullPage → FullPage（仅用户显式触发）
 *   否则：
 *     Readability 主 → 质量评估
 *       good / warning → 采用（warning 保留警告）
 *       failed / poor  → Defuddle 回退 → chooseBetter
 *       Readability 无内容时 → Semantic DOM 兜底
 */
import type { EngineResult, ExtractionContext, ExtractionResult, QualityReport } from '../shared/types';
import { runFullPage, fullPageEngineId } from './engines/full-page-engine';
import { readabilityEngineId, runReadability } from './engines/readability-engine';
import { runDefuddle, defuddleEngineId } from './engines/defuddle-engine';
import { runSemanticDom, semanticDomEngineId } from './engines/semantic-dom-engine';
import { runSelectedElement, selectedElementEngineId } from './engines/selected-element-engine';
import { computeQuality } from './quality-gate';
import { mergeMetadata } from '../metadata/metadata-merger';
import { makeTurndown } from '../markdown/turndown-service';
import { buildFrontMatter } from '../markdown/frontmatter';
import { buildCleanDoc } from '../content/build-document';
import { removeNoise } from '../normalize/sanitize';
import { absolutize } from '../normalize/links';
import { preserveCodeLanguage } from '../normalize/code';
import { matchAdapter, type SiteAdapter } from '../adapters';

/**
 * 为单个引擎准备独立、干净的 document 副本。
 * 引擎（Readability/Defuddle）都会修改传入的 document，且规范化是引擎无关前置，
 * 故每次调用都从原始 context.document 重新克隆并规范化。
 * 若命中站点适配器，追加其 removeSelectors 与 beforeExtract 修正。
 */
function prepareEngineDoc(context: ExtractionContext, adapter?: SiteAdapter | null): Document {
  const doc = buildCleanDoc(context.document);
  removeNoise(doc);
  absolutize(doc, context.url);
  preserveCodeLanguage(doc);
  if (adapter) {
    if (adapter.removeSelectors?.length) {
      const extra: Element[] = [];
      doc.querySelectorAll(adapter.removeSelectors.join(',')).forEach((el) => extra.push(el));
      for (const el of extra) el.parentNode?.removeChild(el);
    }
    adapter.beforeExtract?.(doc, context.url);
  }
  return doc;
}

/**
 * 为适配器选择器准备页面副本。
 * 适配器已经精确指定正文容器，因此先定位正文，不执行可能误删其布局祖先的全页噪声清理。
 */
function prepareAdapterDoc(context: ExtractionContext, adapter: SiteAdapter): Document {
  const doc = buildCleanDoc(context.document);
  absolutize(doc, context.url);
  preserveCodeLanguage(doc);
  if (adapter.removeSelectors?.length) {
    const extra: Element[] = [];
    doc.querySelectorAll(adapter.removeSelectors.join(',')).forEach((el) => extra.push(el));
    for (const el of extra) el.parentNode?.removeChild(el);
  }
  adapter.beforeExtract?.(doc, context.url);
  return doc;
}

/** 适配器指定正文容器：按 preferredContentSelector 依次尝试，内容足够则采用 */
function runAdapterSelector(doc: Document, selectors: string[]): EngineResult | null {
  for (const selector of selectors) {
    const el = doc.querySelector(selector);
    if (el && (el.textContent ?? '').trim().length >= 100) {
      return {
        engineId: 'adapter',
        html: el.innerHTML,
        metadata: {},
        durationMs: 0,
        diagnostics: { selector, removals: [] },
      };
    }
  }
  return null;
}

/** 用适配器的 metadataSelectors 补充/修正元数据（从页面元素提取文本） */
function applyAdapterMetadata(
  metadata: import('../shared/types').ArticleMetadata,
  doc: Document,
  adapter: SiteAdapter
): void {
  const sels = adapter.metadataSelectors;
  if (!sels) return;
  // 标题：适配器选择器优先（如去掉站点后缀的干净标题）
  if (sels.title) {
    const el = doc.querySelector(sels.title);
    const t = el?.textContent?.trim();
    if (t && t.length < 200) metadata.title = t;
  }
  if (!metadata.author && sels.author) {
    const el = doc.querySelector(sels.author);
    const t = el?.textContent?.trim();
    if (t && t.length < 100) metadata.author = t;
  }
  if (!metadata.publishedAt && sels.publishedAt) {
    const el = doc.querySelector(sels.publishedAt);
    const t = el?.textContent?.trim();
    if (t) metadata.publishedAt = t;
  }
}

const LEVEL_RANK: Record<string, number> = { good: 3, warning: 2, poor: 1, failed: 0 };

function countMetrics(md: string): { charCount: number; paragraphs: number } {
  return {
    charCount: md.replace(/\s/g, '').length,
    paragraphs: md.split(/\n\s*\n/).filter((p) => p.trim()).length,
  };
}

/** 同等级时：取字符显著更多且链接占比不失控的结果 */
function isBetter(fb: QualityReport, pr: QualityReport): boolean {
  if (fb.metrics.linkRatio > 60 && (pr.metrics.linkRatio ?? 0) <= 60) return false;
  return (fb.metrics.charCount ?? 0) > (pr.metrics.charCount ?? 0) * 1.2;
}

function fail(context: ExtractionContext, error: string, why: string): ExtractionResult {
  return {
    ok: false,
    error,
    markdown: '',
    metadata: mergeMetadata({}, context.document, context.url),
    quality: { level: 'failed', warnings: [why], metrics: {} },
    charCount: 0,
    paragraphs: 0,
    fallback: true,
  };
}

function finalize(engineResult: EngineResult, engineId: string, context: ExtractionContext, adapter?: SiteAdapter | null): ExtractionResult {
  const html = engineResult.html ?? '';
  let md: string;
  try {
    md = makeTurndown().turndown(html);
  } catch (e) {
    return fail(context, 'Markdown 转换失败：' + (e as Error).message, 'Markdown 转换失败');
  }
  if (!md.trim()) {
    return fail(context, '页面没有可转换的正文内容（可能为空白页、纯 JS 渲染或登录墙）', '转换为空内容');
  }

  const metadata = mergeMetadata(engineResult.metadata, context.document, context.url);
  if (adapter) applyAdapterMetadata(metadata, context.document, adapter);
  const metrics = countMetrics(md);
  const quality = computeQuality(md, metrics);
  const markdown = buildFrontMatter(metadata, quality, engineId) + md;

  return {
    ok: true,
    engineId,
    markdown,
    metadata,
    quality,
    charCount: metrics.charCount,
    paragraphs: metrics.paragraphs,
    fallback: engineId !== readabilityEngineId,
  };
}

/** 选中文本提取：读取活动页面选中内容，走完整输出管线（Front Matter/质量） */
function extractSelection(context: ExtractionContext): ExtractionResult {
  const sourceDoc = (globalThis as { document?: Document }).document || context.document;
  const sel = runSelectedElement(sourceDoc);
  if (!sel) {
    return fail(context, '未检测到选中文本，请先在页面中选中内容再点击"提取选中"', '无选中内容');
  }
  let md: string;
  try {
    md = makeTurndown().turndown(sel.html ?? '');
  } catch (e) {
    return fail(context, 'Markdown 转换失败：' + (e as Error).message, 'Markdown 转换失败');
  }
  if (!md.trim()) {
    return fail(context, '选中内容为空', '选中内容为空');
  }
  const metadata = mergeMetadata(sel.metadata, context.document, context.url);
  const metrics = countMetrics(md);
  const quality = computeQuality(md, metrics);
  return {
    ok: true,
    engineId: selectedElementEngineId,
    markdown: buildFrontMatter(metadata, quality, selectedElementEngineId) + md,
    metadata,
    quality,
    charCount: metrics.charCount,
    paragraphs: metrics.paragraphs,
    fallback: true,
  };
}

export function extractPage(context: ExtractionContext): ExtractionResult {
  const adapter = matchAdapter(context.url);

  if (context.useSelection) {
    return extractSelection(context);
  }
  if (context.forceFullPage) {
    return finalize(runFullPage({ ...context, document: prepareEngineDoc(context, adapter) }), fullPageEngineId, context, adapter);
  }

  // 0) 适配器指定正文容器优先（仅当命中且提取到足够内容）
  if (adapter?.preferredContentSelector?.length) {
    const adapterDoc = prepareAdapterDoc(context, adapter);
    const adapterRes = runAdapterSelector(adapterDoc, adapter.preferredContentSelector);
    if (adapterRes) {
      const adapterMd = makeTurndown().turndown(adapterRes.html ?? '');
      const adapterQuality = computeQuality(adapterMd, countMetrics(adapterMd));
      if (adapterQuality.level === 'good' || adapterQuality.level === 'warning') {
        return finalize(adapterRes, 'adapter:' + adapter.id, context, adapter);
      }
    }
  }

  // 1) 主引擎：Readability（独立副本）
  const primary = runReadability({ ...context, document: prepareEngineDoc(context, adapter) });
  const primaryMd = primary.html ? makeTurndown().turndown(primary.html) : '';
  const primaryQuality = computeQuality(primaryMd, countMetrics(primaryMd));
  let chosen = primary;
  let engineId = readabilityEngineId;

  // 2) 主结果 failed/poor → Defuddle 回退（独立副本，避免被主引擎污染）
  if (primaryQuality.level === 'failed' || primaryQuality.level === 'poor') {
    const fallback = runDefuddle({ ...context, document: prepareEngineDoc(context, adapter) });
    const fallbackMd = fallback.html ? makeTurndown().turndown(fallback.html) : '';
    const fallbackQuality = computeQuality(fallbackMd, countMetrics(fallbackMd));
    if (
      fallback.html &&
      fallbackQuality.level !== 'failed' &&
      (LEVEL_RANK[fallbackQuality.level] > LEVEL_RANK[primaryQuality.level] ||
        isBetter(fallbackQuality, primaryQuality))
    ) {
      chosen = fallback;
      engineId = defuddleEngineId;
    } else if (!primary.html) {
      // 3) Readability 完全无内容 → Semantic DOM 兜底
      const semantic = runSemanticDom({ ...context, document: prepareEngineDoc(context, adapter) });
      if (semantic.html) {
        chosen = semantic;
        engineId = semanticDomEngineId;
      }
    }
  }

  return finalize(chosen, engineId, context, adapter);
}
