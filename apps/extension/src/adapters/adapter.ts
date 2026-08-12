/**
 * 站点适配器接口（V2 §8.3）：轻量"提示与修正"，而非完全替代引擎。
 * 适配器失败必须安全回退到通用引擎。
 */
export interface SiteAdapter {
  /** 适配器标识（如 'weixin'） */
  id: string;
  /** 匹配的域名（用于快速判断） */
  hosts: string[];
  /** 完整匹配逻辑（默认按 hosts 匹配，可覆盖） */
  match(url: string): boolean;
  /** 优先正文容器选择器（按顺序尝试，命中且内容足够则直接使用） */
  preferredContentSelector?: string[];
  /** 额外需要移除的噪音容器选择器（追加到通用 removeNoise 之后） */
  removeSelectors?: string[];
  /** 元数据修正选择器（从页面元素提取文本） */
  metadataSelectors?: {
    title?: string;
    author?: string;
    publishedAt?: string;
  };
  /** 提取前对 document 副本的修正（如标记节点、补充属性） */
  beforeExtract?(doc: Document, url: string): void;
}
