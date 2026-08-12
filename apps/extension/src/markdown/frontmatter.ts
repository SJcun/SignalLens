/**
 * YAML Front Matter 生成（V2 §11.4 输出结构，阶段 1 先落地基础字段）。
 */
import type { ArticleMetadata, QualityReport } from '../shared/types';

const quote = (s: string): string => `"${s.replace(/"/g, '\\"')}"`;

export function buildFrontMatter(
  metadata: ArticleMetadata,
  quality: QualityReport,
  extractor: string
): string {
  const lines: string[] = ['---'];
  lines.push(`title: ${quote(metadata.title)}`);
  if (metadata.author) lines.push(`author: ${quote(metadata.author)}`);
  lines.push(`source: ${quote(metadata.source)}`);
  if (metadata.site) lines.push(`site: ${quote(metadata.site)}`);
  if (metadata.publishedAt) lines.push(`published_at: ${quote(metadata.publishedAt)}`);
  lines.push(`captured_at: ${quote(metadata.capturedAt)}`);
  if (metadata.language) lines.push(`language: ${quote(metadata.language)}`);
  lines.push(`extractor: ${quote(extractor)}`);
  lines.push(`quality: ${quote(quality.level)}`);
  if (quality.warnings.length) {
    lines.push(`warnings:`);
    for (const w of quality.warnings) lines.push(`  - ${quote(w)}`);
  } else {
    lines.push('warnings: []');
  }
  lines.push('---');
  return lines.join('\n') + '\n';
}
