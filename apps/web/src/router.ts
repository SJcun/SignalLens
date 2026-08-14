import { createRouter, createWebHistory } from 'vue-router'

import { hasAccessToken } from './auth'
import AccountView from './views/AccountView.vue'
import AnalysisScheduleView from './views/AnalysisScheduleView.vue'
import ContentDetailView from './views/ContentDetailView.vue'
import InboxView from './views/InboxView.vue'
import LoginView from './views/LoginView.vue'
import PreferencesView from './views/PreferencesView.vue'
import StatsView from './views/StatsView.vue'

/** 登录页公开，其余页面必须持有后端会话令牌。 */
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/inbox' },
    { path: '/inbox', component: InboxView },
    { path: '/contents/:contentId', component: ContentDetailView },
    { path: '/preferences', component: PreferencesView },
    { path: '/analysis-schedule', component: AnalysisScheduleView },
    { path: '/stats', component: StatsView },
    { path: '/account', component: AccountView },
    { path: '/login', component: LoginView, meta: { public: true } },
  ],
})

router.beforeEach((to) => {
  const loggedIn = hasAccessToken()
  if (to.meta.public && loggedIn) return '/inbox'
  if (!to.meta.public && !loggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  return true
})
