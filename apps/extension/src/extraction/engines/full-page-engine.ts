/**
 * FullPage 引擎：仅在用户明确点击"强制整页转换"时运行（V2 §7.5），
 * 永远标记低置信度，不进入自动成功链路。
 */
import type { EngineResult, ExtractionContext } from '../../shared/types';

export const fullPageEngineId = 'full-page';

export function runFullPage(context: ExtractionContext): EngineResult {
  const t0 = performance.now();
  const html = context.document.body ? context.document.body.innerHTML : '';
  const durationMs = performance.now() - t0;
  return {
    engineId: fullPageEngineId,
    html,
    metadata: { title: context.document.title || undefined },
    durationMs,
    diagnostics: { selector: 'body', removals: [] },
  };
}
