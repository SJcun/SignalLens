import { VueQueryPlugin } from '@tanstack/vue-query'
import { createApp } from 'vue'

import App from './App.vue'
import { router } from './router'
import './styles.css'

/** 创建 Web 应用并挂载路由和服务端状态缓存。 */
createApp(App).use(router).use(VueQueryPlugin).mount('#app')

