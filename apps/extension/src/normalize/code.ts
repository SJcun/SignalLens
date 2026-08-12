/**
 * 代码块语言保留：在提取前把 <code> 的 language-* class 存入 data-lang，
 * 供 Turndown 规则输出围栏语言（修复基线缺陷 2）。
 */
export function preserveCodeLanguage(doc: Document): void {
  doc.querySelectorAll('code').forEach((el) => {
    if (el.getAttribute('data-lang')) return;
    const cls = Array.from(el.classList).find((c) => c.startsWith('language-'));
    if (cls) {
      el.setAttribute('data-lang', cls.slice('language-'.length));
    }
  });
}

/** Turndown 代码块规则：优先读 data-lang，其次 class 中的 language- */
export function codeLanguageOf(el: Element): string {
  const fromData = el.getAttribute('data-lang');
  if (fromData) return fromData;
  const fromClass = Array.from(el.classList).find((c) => c.startsWith('language-'));
  return fromClass ? fromClass.slice('language-'.length) : '';
}
