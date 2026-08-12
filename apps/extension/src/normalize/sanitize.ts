/**
 * 噪音容器清理：在提取前移除导航、页眉页脚、广告、评论区、相关推荐等。
 * （原 extract.js 的 NOISE_SELECTORS / removeNoise 迁移至此）
 */
export const NOISE_SELECTORS = [
  'nav', 'header', 'footer', 'aside',
  'form', 'iframe', 'script', 'style', 'noscript', 'template',
  '[class*="advertisement"]', '[id*="advertisement"]',
  '[class*="ad-"]', '[id*="ad-"]', '[class*="ads"]', '[id*="ads"]',
  '[class*="comment"]', '[id*="comment"]',
  '[class*="related"]', '[class*="recommend"]', '[class*="share"]',
  '[class*="footer"]', '[class*="header"]', '[class*="nav"]', '[class*="navbar"]',
];

export function removeNoise(doc: Document): void {
  const toRemove: Element[] = [];
  doc.querySelectorAll(NOISE_SELECTORS.join(',')).forEach((el) => toRemove.push(el));
  for (const el of toRemove) {
    el.parentNode?.removeChild(el);
  }
}
