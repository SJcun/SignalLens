/**
 * Defuddle 引擎（V2 阶段 2 引入的对照引擎）：
 * - core bundle（'defuddle' 主入口），出 HTML + 元数据 + debug
 * - useAsync: false —— 安全要求，全本地处理，禁止第三方 API（如 FxTwitter）
 * - 本阶段不改变默认引擎；结果用于与 Readability 双引擎比较
 */
import Defuddle, { type DefuddleResponse } from 'defuddle';
import type { EngineResult, ExtractionContext } from '../../shared/types';

export const defuddleEngineId = 'defuddle';

export function runDefuddle(context: ExtractionContext): EngineResult {
  const t0 = performance.now();
  let response: DefuddleResponse | null = null;
  try {
    response = new Defuddle(context.document, {
      useAsync: false,
      debug: !!context.debug,
    }).parse();
  } catch (e) {
    return {
      engineId: defuddleEngineId,
      metadata: {},
      durationMs: performance.now() - t0,
      diagnostics: {
        removals: [{ reason: 'Defuddle 抛错: ' + (e as Error).message }],
      },
    };
  }
  const durationMs = performance.now() - t0;

  if (!response || !response.content) {
    return { engineId: defuddleEngineId, metadata: {}, durationMs };
  }
  return {
    engineId: defuddleEngineId,
    html: response.content,
    metadata: {
      title: response.title || undefined,
      author: response.author || undefined,
      site: response.site || undefined,
      publishedAt: response.published || undefined,
    },
    durationMs,
    diagnostics: {
      selector: response.debug?.contentSelector || undefined,
      removals: (response.debug?.removals || []).map((r) => ({
        selector: r.selector,
        reason: r.reason || 'removed',
      })),
    },
  };
}
