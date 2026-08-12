/**
 * 内置站点适配器集合：仅包含经真实失败数据验证需要的站点。
 * 添加新站点前：先加 fixture → 复现失败 → 写适配器 → 测试 → 注册。
 */
import { registerAdapter } from '../registry';
import { bestblogsAdapter } from './bestblogs';

/** 在 content script 入口注册全部内置适配器（幂等） */
let registered = false;
export function registerBuiltinAdapters(): void {
  if (registered) return;
  registered = true;
  registerAdapter(bestblogsAdapter);
}
