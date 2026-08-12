import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'

import App from './App.vue'

describe('App', () => {
  it('展示产品名称和核心导航', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div>测试页面</div>' } },
        { path: '/inbox', component: { template: '<div>Inbox</div>' } },
        { path: '/preferences', component: { template: '<div>阅读偏好</div>' } },
        { path: '/stats', component: { template: '<div>统计</div>' } },
        { path: '/account', component: { template: '<div>账户</div>' } },
      ],
    })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(App, { global: { plugins: [router] } })
    expect(wrapper.text()).toContain('SignalLens')
    expect(wrapper.text()).toContain('Inbox')
  })
})
