/// <reference types="vitest/config" />

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

/** Web 开发、测试和 API 代理的统一配置。 */
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'happy-dom',
  },
})
