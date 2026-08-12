/**
 * 质量门禁（阶段 1 基础版）：计算基础指标并给出等级与警告。
 * 完整门禁（触发回退、多引擎比较）在阶段 3 实现（V2 §10）。
 */
import type { QualityLevel, QualityReport } from '../shared/types';

// 登录墙强信号关键词（避免正文正常提到"登录"造成误报）
const LOGIN_KEYWORDS = [
  '请登录', '登录后', '登录账号', '登录会员', '登录查看', '登录阅读',
  'sign in', 'login to', '会员专享', '付费阅读', '订阅后可', '加入会员', '开通会员',
];

const countTables = (md: string): number => {
  let tables = 0;
  let inTable = false;
  for (const line of md.split('\n')) {
    if (/^\|/.test(line)) {
      if (!inTable) tables++;
      inTable = true;
    } else {
      inTable = false;
    }
  }
  return tables;
};

export function computeQuality(
  md: string,
  raw: { charCount: number; paragraphs: number }
): QualityReport {
  const warnings: string[] = [];
  const links = md.match(/\[[^\]]*\]\([^)]*\)/g) || [];
  const linkTextLen = links.reduce((sum, l) => sum + l.length, 0);
  const metrics: Record<string, number> = {
    charCount: raw.charCount,
    paragraphs: raw.paragraphs,
    linkRatio: md.length ? Math.round((linkTextLen / md.length) * 100) : 0,
    headings: (md.match(/^#{1,6} /gm) || []).length,
    codeBlocks: Math.floor((md.match(/```/g) || []).length / 2),
    tables: countTables(md),
    images: (md.match(/!\[[^\]]*\]\([^)]*\)/g) || []).length,
  };

  let level: QualityLevel = 'good';

  if (raw.charCount === 0) {
    return { level: 'failed', warnings: ['没有提取到任何内容'], metrics };
  }
  if (raw.charCount < 100) {
    level = 'poor';
    warnings.push('正文过短（<100 字符），疑似提取失败或页面无正文');
  } else if (raw.charCount < 300) {
    if (level === 'good') level = 'warning';
    warnings.push('正文较短（<300 字符）');
  }

  if (LOGIN_KEYWORDS.some((k) => md.includes(k))) {
    if (level === 'good') level = 'warning';
    warnings.push('检测到登录/付费相关文案，可能为登录墙页面');
  }

  if (metrics.linkRatio > 60 && raw.charCount < 2000) {
    if (level === 'good') level = 'warning';
    warnings.push('链接占比过高，疑似列表/导航页而非正文');
  }

  if (!metrics.headings && raw.charCount > 500) {
    if (level === 'good') level = 'warning';
    warnings.push('正文缺少标题结构');
  }

  // 重复段落检测（模板/复制内容嫌疑）
  const paras = md.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  const uniqueParas = new Set(paras);
  if (paras.length >= 4 && paras.length - uniqueParas.size >= Math.max(2, Math.round(paras.length * 0.2))) {
    if (level === 'good') level = 'warning';
    metrics.duplicateRatio = Math.round(((paras.length - uniqueParas.size) / paras.length) * 100);
    warnings.push(`检测到重复段落（重复比 ${metrics.duplicateRatio}%），疑似模板/复制内容`);
  }

  return { level, warnings, metrics };
}
