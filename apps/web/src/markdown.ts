import createDOMPurify from 'dompurify'
import { Marked } from 'marked'

const markdownParser = new Marked({ gfm: true, breaks: false })
const htmlSanitizer = createDOMPurify(window)

markdownParser.use({
  renderer: {
    /** 正文来自外部网页；丢弃原始 HTML，只渲染 Markdown 语法生成的标签。 */
    html() {
      return ''
    },
    /** 页面标题已经使用 h1，正文标题整体下移一级以保持正确文档层级。 */
    heading({ tokens, depth }) {
      const level = Math.min(depth + 1, 6)
      return `<h${level}>${this.parser.parseInline(tokens)}</h${level}>\n`
    },
  },
})

/** 移除 PageSift 生成的 YAML frontmatter，仅保留用户需要阅读的正文。 */
export function stripFrontmatter(markdown: string): string {
  const match = markdown.match(/^---\r?\n([\s\S]*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/)
  if (!match || !/^[A-Za-z_][\w-]*\s*:/m.test(match[1])) return markdown
  return markdown.slice(match[0].length)
}

/** 将不可信 Markdown 转换为净化后的 HTML，并规范外部链接和图片属性。 */
export function renderMarkdown(markdown: string, sourceUrl?: string): string {
  const body = stripFrontmatter(markdown)
  const parsed = markdownParser.parse(body, { async: false }) as string
  const sanitized = htmlSanitizer.sanitize(parsed)
  const template = document.createElement('template')
  template.innerHTML = sanitized

  template.content.querySelectorAll('a[href]').forEach((link) => {
    const href = link.getAttribute('href')
    if (!href) return
    try {
      const absoluteUrl = new URL(href, sourceUrl || window.location.href)
      link.setAttribute('href', absoluteUrl.href)
      if (absoluteUrl.protocol === 'http:' || absoluteUrl.protocol === 'https:') {
        link.setAttribute('target', '_blank')
        link.setAttribute('rel', 'noopener noreferrer')
      }
    } catch {
      link.removeAttribute('href')
    }
  })

  template.content.querySelectorAll('img[src]').forEach((image) => {
    const src = image.getAttribute('src')
    if (!src) return
    try {
      image.setAttribute('src', new URL(src, sourceUrl || window.location.href).href)
      image.setAttribute('loading', 'lazy')
      image.setAttribute('decoding', 'async')
      image.setAttribute('referrerpolicy', 'no-referrer')
    } catch {
      image.remove()
    }
  })

  return template.innerHTML
}
