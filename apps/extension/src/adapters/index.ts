/**
 * 适配器集合：站点规则按真实失败数据逐个添加（V2 §8 原则）。
 * 目前无内置站点规则（掘金/CSDN/博客园经真实页面验证已被通用引擎覆盖，
 * 微信公众号待真实链接样本）。
 */
export type { SiteAdapter } from './adapter';
export { registerAdapter, matchAdapter, listAdapters } from './registry';
