/**
 * Readability 引擎：当前主引擎（V1 核心，阶段 1 保持主位；阶段 3 按基线数据定默认）。
 */
import type { EngineResult, ExtractionContext } from '../../shared/types';

export const readabilityEngineId = 'readability';

export function runReadability(context: ExtractionContext): EngineResult {
  const t0 = performance.now();
  let article: ReadabilityParseResult | null = null;
  try {
    article = new Readability(context.document).parse();
  } catch (e) {
    return {
      engineId: readabilityEngineId,
      metadata: {},
      durationMs: performance.now() - t0,
      diagnostics: { selector: undefined, removals: [{ reason: 'Readability 抛错: ' + (e as Error).message }] },
    };
  }
  const durationMs = performance.now() - t0;

  if (!article || !article.content) {
    return { engineId: readabilityEngineId, metadata: {}, durationMs };
  }
  return {
    engineId: readabilityEngineId,
    html: article.content,
    metadata: {
      title: article.title || undefined,
      author: article.byline || undefined,
      site: article.siteName || undefined,
      publishedAt: article.publishedTime || undefined,
    },
    durationMs,
    diagnostics: { selector: 'readability-auto', removals: [] },
  };
}
