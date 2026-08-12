// @vitest-environment jsdom

import { describe, expect, it } from 'vitest'

import { renderMarkdown, stripFrontmatter } from './markdown'

describe('Markdown 正文渲染', () => {
  it('隐藏 frontmatter 并渲染常用 GFM 结构', () => {
    const markdown = `---
title: 测试文章
site: example.com
---
# 一级标题

- 要点一
- 要点二

| 字段 | 内容 |
| --- | --- |
| 状态 | 完成 |
`
    const html = renderMarkdown(markdown)
    expect(html).not.toContain('site: example.com')
    expect(html).toContain('<h2>一级标题</h2>')
    expect(html).toContain('<li>要点一</li>')
    expect(html).toContain('<table>')
  })

  it('移除原始 HTML 和危险属性', () => {
    const html = renderMarkdown(`
# 安全正文

<script>alert('xss')</script>
<img src="x" onerror="alert('xss')">
`)
    expect(html).toContain('<h2>安全正文</h2>')
    expect(html).not.toContain('<script')
    expect(html).not.toContain('onerror')
  })

  it('将相对链接和图片转换为基于原文地址的绝对地址', () => {
    const html = renderMarkdown(
      '[章节](/guide)\n\n![示意图](images/diagram.png)',
      'https://example.com/posts/article',
    )
    expect(html).toContain('href="https://example.com/guide"')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('src="https://example.com/posts/images/diagram.png"')
    expect(html).toContain('loading="lazy"')
  })

  it('普通分隔线不会被误判为 frontmatter', () => {
    expect(stripFrontmatter('---\n\n正文')).toBe('---\n\n正文')
  })
})
