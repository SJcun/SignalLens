export type Theme = 'dark' | 'light'

/** 主题只保存在当前浏览器，不与账户或后端数据绑定。 */
const THEME_STORAGE_KEY = 'signallens.theme'

/** 判断本地存储值是否是当前支持的主题。 */
function isTheme(value: string | null): value is Theme {
  return value === 'dark' || value === 'light'
}

/** 把主题写入根节点，供全局 CSS 变量立即生效。 */
function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
}

/** 页面启动时恢复用户选择；无有效设置时保持现有深色默认值。 */
export function initializeTheme(): Theme {
  const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY)
  const theme = isTheme(storedTheme) ? storedTheme : 'dark'
  applyTheme(theme)
  return theme
}

/** 用户主动切换后同步更新页面并持久化选择。 */
export function setTheme(theme: Theme): void {
  applyTheme(theme)
  window.localStorage.setItem(THEME_STORAGE_KEY, theme)
}
