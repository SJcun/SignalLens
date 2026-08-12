/** 动态正文等待选项。 */
export interface ContentReadinessOptions {
  /** 正文达到该字符数后才视为可提取。 */
  minChars?: number;
  /** 最长等待时间，避免 popup 一直处于忙碌状态。 */
  timeoutMs?: number;
  /** 正文长度保持不变达到该时长后，才视为渲染稳定。 */
  settleMs?: number;
}

/** 缓存结果中与安全复用相关的最小字段。 */
export interface CachedExtractionResult {
  ok?: boolean;
  quality?: string;
}

/** 判断任一适配器正文容器是否已经包含足够内容。 */
export function isAdapterContentReady(
  doc: Document,
  selectors: string[],
  minChars = 100
): boolean {
  return selectors.some((selector) => {
    const text = doc.querySelector(selector)?.textContent ?? '';
    return text.trim().length >= minChars;
  });
}

/** 返回所有候选正文容器中的最大文本长度。 */
function getAdapterContentLength(doc: Document, selectors: string[]): number {
  return Math.max(
    0,
    ...selectors.map((selector) => (doc.querySelector(selector)?.textContent ?? '').trim().length)
  );
}

/**
 * 等待动态站点把正文写入 DOM。
 * 先监听再复查可避免“首次检查之后、观察器启动之前”发生变更时漏掉通知。
 */
export async function waitForAdapterContent(
  doc: Document,
  selectors: string[],
  options: ContentReadinessOptions = {}
): Promise<boolean> {
  const minChars = options.minChars ?? 100;
  const timeoutMs = options.timeoutMs ?? 120_000;
  const settleMs = options.settleMs ?? 500;

  return new Promise((resolve) => {
    let settled = false;
    let timeoutId: ReturnType<typeof setTimeout>;
    let settleId: ReturnType<typeof setTimeout> | undefined;
    let observedLength = -1;
    const Observer = doc.defaultView?.MutationObserver ?? globalThis.MutationObserver;
    const observer = new Observer(() => checkReadiness());

    const finish = (ready: boolean): void => {
      if (settled) return;
      settled = true;
      observer.disconnect();
      clearTimeout(timeoutId);
      if (settleId) clearTimeout(settleId);
      resolve(ready);
    };

    /** 仅在正文长度发生变化时重置稳定计时，避免页面其他动画导致永远无法完成。 */
    const checkReadiness = (): void => {
      const length = getAdapterContentLength(doc, selectors);
      if (length === observedLength) return;
      observedLength = length;
      if (settleId) clearTimeout(settleId);
      if (length < minChars) return;
      settleId = setTimeout(() => {
        const currentLength = getAdapterContentLength(doc, selectors);
        if (currentLength === length && currentLength >= minChars) finish(true);
        else checkReadiness();
      }, settleMs);
    };

    observer.observe(doc.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    timeoutId = setTimeout(() => finish(isAdapterContentReady(doc, selectors, minChars)), timeoutMs);

    // 观察器启动后立即检查，封住初始读取与 observe 之间的竞态窗口。
    checkReadiness();
  });
}

/** 仅复用同一 URL 的高质量成功结果，避免缓存静态摘要或 SPA 上一篇文章。 */
export function isReusableExtractionResult(
  cached: CachedExtractionResult | undefined,
  cachedUrl: string | undefined,
  currentUrl: string
): boolean {
  return !!cached?.ok && cached.quality === 'good' && cachedUrl === currentUrl;
}
