import { createRouter, createWebHistory } from 'vue-router'

import ContentDetailView from './views/ContentDetailView.vue'
import InboxView from './views/InboxView.vue'
import PreferencesView from './views/PreferencesView.vue'
import StatsView from './views/StatsView.vue'

/** SignalLens V0.1 的四个核心页面路由。 */
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/inbox' },
    { path: '/inbox', component: InboxView },
    { path: '/contents/:contentId', component: ContentDetailView },
    { path: '/preferences', component: PreferencesView },
    { path: '/stats', component: StatsView },
  ],
})

