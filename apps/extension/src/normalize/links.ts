/**
 * 链接与图片规范化：
 * 1. 相对路径 → 绝对 URL（基于页面 baseURI）
 * 2. data-src / data-srcset 懒加载 → 提升为 src（修复基线缺陷 1）
 * 3. 过滤 javascript: 等危险协议（安全要求）
 */
export function absolutize(root: ParentNode, baseUrl: string): void {
  // 注意：不能用 root.baseURI —— 重建文档（createHTMLDocument）的 baseURI 是 about:blank，
  // 必须用传入的原页面 baseUrl。
  const base = (() => {
    try {
      return new URL(baseUrl);
    } catch {
      return new URL('https://invalid.invalid');
    }
  })();

  root.querySelectorAll('img, video, source, a').forEach((el) => {
    if (el.tagName === 'IMG') {
      // 微信等站点会在 src 中放 data:image 占位图，真实地址仍保存在懒加载属性中。
      const lazySrc =
        el.getAttribute('data-src') ||
        el.getAttribute('data-original') ||
        el.getAttribute('data-lazy-src');
      const currentSrc = el.getAttribute('src')?.trim() ?? '';
      if (lazySrc && (!currentSrc || /^data:image\//i.test(currentSrc))) {
        const resolved = safeUrl(lazySrc, base);
        if (resolved) el.setAttribute('src', resolved);
      }

      // 响应式懒加载图片只有 data-srcset 时，也要提升并绝对化全部候选地址。
      const lazySrcset = el.getAttribute('data-srcset');
      if (!el.getAttribute('srcset') && lazySrcset) {
        const resolved = absolutizeSrcset(lazySrcset, base);
        if (resolved) el.setAttribute('srcset', resolved);
      }
    }
    if (el.tagName === 'SOURCE' && !el.getAttribute('src') && el.getAttribute('data-src')) {
      const resolved = safeUrl(el.getAttribute('data-src') as string, base);
      if (resolved) el.setAttribute('src', resolved);
    }

    for (const attr of ['src', 'href', 'srcset', 'poster']) {
      const raw = el.getAttribute(attr);
      if (!raw) continue;
      // 逗号拆分仅适用于 srcset（多候选）；href 等直接由 URL 构造器处理（自动编码空格/保留逗号）
      const value = attr === 'srcset' ? absolutizeSrcset(raw, base) : safeUrl(raw, base);
      if (value) el.setAttribute(attr, value);
    }
  });
}

/** srcset 允许多个 "url 描述符" 候选，以逗号分隔 */
function absolutizeSrcset(raw: string, base: URL): string | null {
  const parts = raw.split(',').map((p) => p.trim());
  return parts
    .map((part) => {
      const [urlPart, ...descriptors] = part.split(/\s+/);
      const abs = safeUrl(urlPart, base);
      return abs ? [abs, ...descriptors].join(' ') : null;
    })
    .filter((p): p is string => p !== null)
    .join(', ');
}

function safeUrl(raw: string, base: URL): string | null {
  if (/^javascript:|^data:text\/html|^vbscript:/i.test(raw)) return null; // 危险协议
  try {
    return new URL(raw, base).href;
  } catch {
    return null;
  }
}
