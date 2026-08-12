/**
 * 将插件 TypeScript 打包成 Manifest V3 可直接加载的本地脚本。
 * 开发环境默认连接本地 API，生产构建通过环境变量覆盖固定地址。
 */
import { build } from 'esbuild'

const apiBaseUrl = process.env.SIGNALLENS_EXTENSION_API_BASE_URL || 'http://localhost:8000/api/v1'
const common = {
  bundle: true,
  format: 'iife',
  target: 'es2022',
  minify: false,
  sourcemap: false,
  logLevel: 'info',
  define: {
    __SIGNALLENS_API_BASE_URL__: JSON.stringify(apiBaseUrl),
  },
}

await Promise.all([
  build({ ...common, entryPoints: ['src/content/content-entry.ts'], outfile: 'dist/content.js' }),
  build({ ...common, entryPoints: ['src/popup/popup.ts'], outfile: 'dist/popup.js' }),
  build({ ...common, entryPoints: ['src/background/service-worker.ts'], outfile: 'dist/service-worker.js' }),
  build({ ...common, entryPoints: ['src/preview/preview.ts'], outfile: 'dist/preview.js' }),
  build({
    ...common,
    format: 'esm',
    entryPoints: ['src/extraction/engines/index.ts'],
    outfile: 'dist/extract-lib.mjs',
  }),
])

console.log(`构建完成，Capture API：${apiBaseUrl}`)

