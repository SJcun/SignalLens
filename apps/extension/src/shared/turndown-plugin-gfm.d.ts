/** Turndown 官方 GFM 扩展只提供 JavaScript，在此声明本项目使用的表格插件入口。 */
declare module 'turndown-plugin-gfm' {
  export const tables: (service: TurndownService) => void;
}
