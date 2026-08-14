/**
 * 引擎库统一入口：esbuild 打包为 dist/extract-lib.mjs（ESM），
 * 供双引擎比较脚本（tests/compare-engines.mjs）与未来的独立预览页复用。
 * 注意：content.js（IIFE，扩展运行时）不依赖此入口，保持默认引擎体积最小。
 */
export { runReadability, readabilityEngineId } from './readability-engine';
export { runDefuddle, defuddleEngineId } from './defuddle-engine';
export { runSemanticDom, semanticDomEngineId } from './semantic-dom-engine';
export { runFullPage, fullPageEngineId } from './full-page-engine';
export { extractPage } from '../orchestrator';
export { computeQuality } from '../quality-gate';
export { makeTurndown } from '../../markdown/turndown-service';
export { countMarkdownTables } from '../../markdown/metrics';
export { removeNoise, NOISE_SELECTORS } from '../../normalize/sanitize';
export { absolutize } from '../../normalize/links';
export { preserveCodeLanguage } from '../../normalize/code';
export { buildCleanDoc } from '../../content/build-document';
export {
  isAdapterContentReady,
  waitForAdapterContent,
  isReusableExtractionResult,
} from '../../content/readiness';
export { registerAdapter, matchAdapter, listAdapters } from '../../adapters';
export { registerBuiltinAdapters } from '../../adapters/sites';
export { buildExportJson, detectContentType, ANALYSIS_ACCESS_RULES } from '../../shared/export';
