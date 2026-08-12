/**
 * Semantic DOM 引擎：仅处理 article / main / [role=main] 语义节点，
 * 作为 Readability 提取不到内容时的轻量回退（V2 §7.3）。
 */
import type { EngineResult, ExtractionContext } from '../../shared/types';

export const semanticDomEngineId = 'semantic-dom';

const SEMANTIC_SELECTOR = 'article, main, [role="main"]';

export function runSemanticDom(context: ExtractionContext): EngineResult {
  const t0 = performance.now();
  const el = context.document.querySelector(SEMANTIC_SELECTOR);
  const durationMs = performance.now() - t0;
  if (!el) {
    return { engineId: semanticDomEngineId, metadata: {}, durationMs };
  }
  return {
    engineId: semanticDomEngineId,
    html: el.innerHTML,
    metadata: { title: context.document.title || undefined },
    durationMs,
    diagnostics: { selector: SEMANTIC_SELECTOR, removals: [] },
  };
}
