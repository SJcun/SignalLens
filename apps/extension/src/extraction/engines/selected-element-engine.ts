/**
 * SelectedElement 引擎：提取浏览器当前选中的文本内容（V2 §7.4）。
 * 优先级最高：用户选中一段后，仅提取选中内容（含其容器结构）。
 */
import { absolutize } from '../../normalize/links';
import type { EngineResult } from '../../shared/types';

export const selectedElementEngineId = 'selection';

/** 从活动文档读取用户选中内容；无选中时返回 null */
export function runSelectedElement(sourceDoc: Document): EngineResult | null {
  const win = sourceDoc.defaultView || globalThis;
  const sel = win.getSelection?.();
  if (!sel || sel.rangeCount === 0) return null;
  const text = sel.toString().trim();
  if (!text) return null;

  const range = sel.getRangeAt(0);
  const container = range.commonAncestorContainer;
  const el = container.nodeType === 1 ? (container as Element) : (container.parentElement as Element);
  if (!el) return null;

  // 克隆选中容器并绝对化链接，避免污染页面
  const holder = sourceDoc.createElement('div');
  holder.appendChild(el.cloneNode(true));
  absolutize(holder, sourceDoc.baseURI || '');

  return {
    engineId: selectedElementEngineId,
    html: holder.innerHTML,
    metadata: { title: sourceDoc.title || undefined },
    durationMs: 0,
    diagnostics: { selector: 'user-selection', removals: [] },
  };
}
