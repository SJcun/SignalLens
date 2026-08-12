/**
 * Turndown 封装：统一配置 + 代码块语言规则 + 相对链接处理。
 */
import { codeLanguageOf } from '../normalize/code';

export interface TurndownLike {
  turndown(input: Node | string): string;
}

export function makeTurndown(): TurndownLike {
  const service = new TurndownService({
    headingStyle: 'atx',
    codeBlockStyle: 'fenced',
    bulletListMarker: '-',
    hr: '---',
  });

  // 代码块：输出带语言的围栏 ```lang
  service.addRule('fencedCodeBlock', {
    filter: (node: Node) =>
      node.nodeName === 'PRE' &&
      (node as HTMLElement).textContent?.includes('\n') !== false,
    replacement: (_content: string, node: Node) => {
      const pre = node as HTMLElement;
      const code = pre.querySelector('code');
      const lang = code ? codeLanguageOf(code) : '';
      const text = pre.textContent?.replace(/\n$/, '') ?? '';
      return `\n\n\`\`\`${lang}\n${text}\n\`\`\`\n\n`;
    },
  });

  return service;
}
