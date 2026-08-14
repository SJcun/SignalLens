import { beforeEach, describe, expect, it } from 'vitest'

import { initializeTheme, setTheme } from './theme'

describe('theme', () => {
  beforeEach(() => {
    window.localStorage.clear()
    delete document.documentElement.dataset.theme
  })

  it('没有有效设置时默认使用深色主题', () => {
    window.localStorage.setItem('signallens.theme', 'unknown')

    expect(initializeTheme()).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('初始化时恢复已保存的浅色主题', () => {
    window.localStorage.setItem('signallens.theme', 'light')

    expect(initializeTheme()).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('切换主题后同时更新页面并保存选择', () => {
    setTheme('light')

    expect(document.documentElement.dataset.theme).toBe('light')
    expect(window.localStorage.getItem('signallens.theme')).toBe('light')
  })
})
