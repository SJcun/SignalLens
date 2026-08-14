import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'

import App from './App.vue'

describe('App', () => {
  beforeEach(() => {
    window.localStorage.clear()
    delete document.documentElement.dataset.theme
  })

  it('展示产品名称和核心导航', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div>测试页面</div>' } },
        { path: '/inbox', component: { template: '<div>Inbox</div>' } },
        { path: '/preferences', component: { template: '<div>阅读偏好</div>' } },
        { path: '/analysis-schedule', component: { template: '<div>整理设置</div>' } },
        { path: '/stats', component: { template: '<div>统计</div>' } },
        { path: '/account', component: { template: '<div>账户</div>' } },
      ],
    })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(App, { global: { plugins: [router] } })
    expect(wrapper.text()).toContain('SignalLens')
    expect(wrapper.text()).toContain('Inbox')
    expect(wrapper.text()).toContain('整理设置')
  })

  it('进入内容详情后仍选中 Inbox 导航', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/inbox', component: { template: '<div>Inbox</div>' } },
        { path: '/contents/:contentId', component: { template: '<div>内容详情</div>' } },
        { path: '/preferences', component: { template: '<div>阅读偏好</div>' } },
        { path: '/analysis-schedule', component: { template: '<div>整理设置</div>' } },
        { path: '/stats', component: { template: '<div>统计</div>' } },
        { path: '/account', component: { template: '<div>账户</div>' } },
      ],
    })
    await router.push('/contents/content-1')
    await router.isReady()

    const wrapper = mount(App, { global: { plugins: [router] } })
    const inboxLink = wrapper.get('nav a[href="/inbox"]')

    expect(inboxLink.classes()).toContain('router-link-active')
  })

  it('切换并保存浅色主题', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/inbox', component: { template: '<div>Inbox</div>' } },
        { path: '/preferences', component: { template: '<div>阅读偏好</div>' } },
        { path: '/analysis-schedule', component: { template: '<div>整理设置</div>' } },
        { path: '/stats', component: { template: '<div>统计</div>' } },
        { path: '/account', component: { template: '<div>账户</div>' } },
      ],
    })
    await router.push('/inbox')
    await router.isReady()

    const wrapper = mount(App, { global: { plugins: [router] } })
    await wrapper.get('button[aria-label="切换到浅色模式"]').trigger('click')

    expect(document.documentElement.dataset.theme).toBe('light')
    expect(window.localStorage.getItem('signallens.theme')).toBe('light')
    expect(wrapper.get('.theme-toggle').attributes('aria-label')).toBe('切换到深色模式')
  })

  it('在登录页也展示主题切换入口', async () => {
    window.localStorage.setItem('signallens.theme', 'light')
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/login',
          component: { template: '<main class="auth-page">登录</main>' },
          meta: { public: true },
        },
      ],
    })
    await router.push('/login')
    await router.isReady()

    const wrapper = mount(App, { global: { plugins: [router] } })

    expect(wrapper.find('.sidebar').exists()).toBe(false)
    expect(wrapper.get('.public-theme-toggle').attributes('aria-label')).toBe('切换到深色模式')
  })
})
