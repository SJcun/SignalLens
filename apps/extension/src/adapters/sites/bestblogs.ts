/**
 * bestblogs.dev 适配器（真实失败数据驱动，2026-08 用户反馈）：
 * - 该站是 Next.js RSC 站点，静态 HTML 正文埋在 flight 数据中（通用引擎只能提取到 meta 摘要）
 * - 浏览器渲染后正文在 #bbArticleContent（prose 容器），"AI 摘要与要点"面板在 article 内但在正文容器外
 * - 适配器用 preferredContentSelector 精确定位正文，同时用 metadataSelectors 修正标题/作者
 */
import type { SiteAdapter } from '../adapter';

export const bestblogsAdapter: SiteAdapter = {
  id: 'bestblogs',
  hosts: ['bestblogs.dev'],
  match: (url: string) => url.includes('bestblogs.dev'),
  preferredContentSelector: ['#bbArticleContent'],
  metadataSelectors: {
    title: '#bbArticleTitle',
    author: 'a[title^="查看该来源"] span.font-medium',
  },
};
