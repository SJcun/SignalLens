/**
 * 元数据合并：从 Readability 结果与页面 meta 标签中提取标题/作者/日期/站点。
 */
import type { ArticleMetadata } from '../shared/types';

export function mergeMetadata(
  partial: Partial<ArticleMetadata>,
  doc: Document,
  url: string
): ArticleMetadata {
  const meta = (name: string): string | null => {
    const el = doc.querySelector(`meta[name="${name}"], meta[property="${name}"]`);
    return el ? el.getAttribute('content')?.trim() || null : null;
  };

  const now = new Date().toISOString();
  return {
    title: partial.title?.trim() || doc.title?.trim() || '未命名文章',
    author: partial.author?.trim() || meta('author') || meta('article:author') || undefined,
    source: url,
    site: partial.site?.trim() || meta('og:site_name') || undefined,
    publishedAt:
      partial.publishedAt?.trim() ||
      meta('article:published_time') ||
      meta('date') ||
      undefined,
    capturedAt: now,
    language: meta('og:locale')?.split('-')[0] || doc.documentElement.lang || undefined,
  };
}
