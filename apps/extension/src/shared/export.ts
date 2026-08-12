/**
 * 文章学习系统对接（V2 §16）：结构化导出格式 + 内容类型识别。
 * 导出 JSON 供后续 7 维度 LLM 写作分析工具消费。
 */
import type { QualityLevel } from './types';

export type { QualityLevel };

export type ContentType =
  | 'article'
  | 'technical-article'
  | 'documentation'
  | 'wiki'
  | 'qa'
  | 'conversation'
  | 'unknown';

/** 基础内容类型识别（V2 §9）：代码块多 → 技术文章；表格多 → 文档类 */
export function detectContentType(input: { codeBlocks: number; tables: number }): ContentType {
  if (input.codeBlocks >= 2) return 'technical-article';
  if (input.tables >= 3) return 'documentation';
  return 'article';
}

export interface ExportInput {
  metadata: {
    title: string;
    source: string;
    capturedAt?: string;
    author?: string;
    publishedAt?: string;
  };
  markdown: string;
  quality: { level: QualityLevel; warnings: string[] };
  extraction: { engine: string };
  metrics: { codeBlocks: number; tables: number };
}

/**
 * 构造学习系统输入 JSON（V2 §16 传输结构）：
 * metadata / markdown / contentType / quality / extraction
 */
export function buildExportJson(input: ExportInput): string {
  const payload = {
    metadata: {
      title: input.metadata.title,
      ...(input.metadata.author ? { author: input.metadata.author } : {}),
      source: input.metadata.source,
      ...(input.metadata.publishedAt ? { published_at: input.metadata.publishedAt } : {}),
    },
    markdown: input.markdown,
    contentType: detectContentType(input.metrics),
    quality: {
      level: input.quality.level,
      warnings: input.quality.warnings,
    },
    extraction: {
      engine: input.extraction.engine,
      adapter: null,
      capturedAt: input.metadata.capturedAt || null,
    },
  };
  return JSON.stringify(payload, null, 2);
}

/**
 * 质量门禁放行规则（V2 §16）：
 * good → 允许直接进入分析；warning → 提示后分析；poor → 必须用户确认；failed → 禁止分析。
 */
export const ANALYSIS_ACCESS_RULES: Record<QualityLevel, string> = {
  good: '允许直接进入分析',
  warning: '显示警告后允许分析',
  poor: '必须用户人工确认后才允许分析',
  failed: '禁止进入分析流程',
};
