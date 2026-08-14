import { VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AnalysisScheduleView from './AnalysisScheduleView.vue'

const apiMocks = vi.hoisted(() => ({
  getAnalysisSchedule: vi.fn(),
  updateAnalysisSchedule: vi.fn(),
}))

vi.mock('../api', () => apiMocks)

describe('AI 整理设置', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.getAnalysisSchedule.mockResolvedValue({
      enabled: false,
      windows: [{ start: '00:00', end: '08:00' }],
      timezone: 'Asia/Shanghai',
      currently_allowed: true,
      next_window_start: null,
      scheduled_job_count: 0,
      updated_at: '2026-08-14T00:00:00Z',
    })
    apiMocks.updateAnalysisSchedule.mockImplementation(async (payload) => ({
      ...payload,
      timezone: 'Asia/Shanghai',
      currently_allowed: true,
      next_window_start: null,
      scheduled_job_count: 0,
      updated_at: '2026-08-14T00:00:00Z',
    }))
  })

  it('切换总开关时立即保存现有窗口', async () => {
    const wrapper = mount(AnalysisScheduleView, {
      global: { plugins: [VueQueryPlugin] },
    })
    await flushPromises()

    await wrapper.get('.switch-control input').setValue(true)
    await flushPromises()

    expect(apiMocks.updateAnalysisSchedule.mock.calls[0][0]).toEqual({
      enabled: true,
      windows: [{ start: '00:00', end: '08:00' }],
    })
    wrapper.unmount()
  })

  it('高价时段关闭模式前提示会被立即释放的任务数', async () => {
    apiMocks.getAnalysisSchedule.mockResolvedValue({
      enabled: true,
      windows: [{ start: '00:00', end: '08:00' }],
      timezone: 'Asia/Shanghai',
      currently_allowed: false,
      next_window_start: '2026-08-14T16:00:00Z',
      scheduled_job_count: 3,
      updated_at: '2026-08-14T00:00:00Z',
    })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const wrapper = mount(AnalysisScheduleView, {
      global: { plugins: [VueQueryPlugin] },
    })
    await flushPromises()

    await wrapper.get('.switch-control input').setValue(false)

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('当前有 3 篇等待整理'))
    expect(apiMocks.updateAnalysisSchedule).not.toHaveBeenCalled()
    confirm.mockRestore()
    wrapper.unmount()
  })
})
