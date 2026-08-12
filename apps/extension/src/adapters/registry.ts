/**
 * 站点适配器注册表：按 URL 匹配适配器。
 * 规则：先注册的优先；未命中返回 null（走通用引擎）。
 * 适配器仅按需添加（真实失败数据驱动），不预先适配大量网站。
 */
import type { SiteAdapter } from './adapter';

const registry: SiteAdapter[] = [];

export function registerAdapter(adapter: SiteAdapter): void {
  // 幂等：同 id 替换
  const idx = registry.findIndex((a) => a.id === adapter.id);
  if (idx >= 0) registry[idx] = adapter;
  else registry.push(adapter);
}

export function matchAdapter(url: string): SiteAdapter | null {
  let host = '';
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return null;
  }
  for (const adapter of registry) {
    if (adapter.hosts.some((h) => host === h || host.endsWith('.' + h))) return adapter;
  }
  return null;
}

export function listAdapters(): string[] {
  return registry.map((a) => a.id);
}
