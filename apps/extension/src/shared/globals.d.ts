/**
 * 第三方库全局声明：Readability / Turndown 以全局脚本（lib/ 下单文件）注入页面，
 * 由 chrome.scripting.executeScript 按顺序执行，故在 TS 中声明为全局。
 */
interface ReadabilityParseResult {
  title?: string;
  byline?: string;
  content?: string;
  textContent?: string;
  length?: number;
  siteName?: string;
  publishedTime?: string;
  [key: string]: unknown;
}

declare class Readability {
  constructor(doc: Document, options?: Record<string, unknown>);
  parse(): ReadabilityParseResult | null;
}

declare class TurndownService {
  constructor(options?: Record<string, unknown>);
  turndown(input: Node | string): string;
  addRule(name: string, rule: {
    filter: unknown;
    replacement?: (content: string, node: Node, options: Record<string, unknown>) => string;
  }): void;
}

interface Window {
  Readability?: typeof Readability;
  TurndownService?: typeof TurndownService;
  __MD_EXTRACT_RAN__?: boolean;
  __MD_EXTRACT_RESULT__?: unknown;
  __MD_VERSION__?: string;
  __MD_EXTRACT_URL__?: string;
  __MD_FORCE_FULL_PAGE__?: boolean;
  __MD_SELECTION_MODE__?: boolean;
  __MD_MANUAL_SELECT__?: boolean;
}
