/**
 * 核心类型定义（对齐 V2 方案 §7 提取引擎抽象）。
 * 阶段 1 先落地结构，质量门禁的完整逻辑在阶段 3 实现。
 */

export type QualityLevel = 'good' | 'warning' | 'poor' | 'failed';

export interface ArticleMetadata {
  title: string;
  author?: string;
  source: string; // 页面 URL
  site?: string;
  publishedAt?: string;
  capturedAt: string; // ISO 时间
  language?: string;
}

export interface QualityReport {
  level: QualityLevel;
  warnings: string[];
  metrics: Record<string, number>;
}

export interface EngineResult {
  engineId: string;
  /** 提取的正文 HTML（交由 Turndown 转换） */
  html?: string;
  /** 引擎直接产出的 Markdown（可选，Defuddle 等引擎可用） */
  markdown?: string;
  metadata: Partial<ArticleMetadata>;
  durationMs: number;
  diagnostics?: {
    selector?: string;
    removals?: Array<{ selector?: string; reason: string }>;
  };
}

/** 提取输入：document 必须是重建后的干净副本（见 content-entry） */
export interface ExtractionContext {
  document: Document;
  url: string;
  forceFullPage?: boolean;
  /** 仅提取浏览器当前选中文本（优先级最高） */
  useSelection?: boolean;
  debug?: boolean;
}

export interface ExtractionResult {
  ok: boolean;
  error?: string;
  engineId?: string;
  /** 最终 Markdown（含 YAML Front Matter） */
  markdown: string;
  metadata: ArticleMetadata;
  quality: QualityReport;
  charCount: number;
  paragraphs: number;
  fallback: boolean;
}
