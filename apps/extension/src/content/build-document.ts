/**
 * 重建干净的 document 副本（供提取引擎使用，避免污染原页面）。
 *
 * Chromium content script 中 document.cloneNode 与 DOMParser 的结果都缺 documentElement
 * （已踩坑验证），须用 createHTMLDocument + 元素级克隆；同时移除其自带空 <title>。
 */
export function buildCleanDoc(source: Document): Document {
  const newDoc = source.implementation.createHTMLDocument('');
  // createHTMLDocument('') 自带空 <title>，需移除，否则克隆的标题会被挤到第二位
  newDoc.head.querySelector('title')?.remove();
  for (const el of Array.from(source.head.children)) {
    if (['title', 'meta', 'base', 'link'].includes(el.tagName.toLowerCase())) {
      newDoc.head.appendChild(el.cloneNode(true));
    }
  }
  for (const el of Array.from(source.body.children)) {
    newDoc.body.appendChild(el.cloneNode(true));
  }
  return newDoc;
}
