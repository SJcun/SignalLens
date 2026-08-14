import { VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'

import ContentDetailView from './ContentDetailView.vue'

const apiMocks = vi.hoisted(() => ({
  getContent: vi.fn(),
  getProfile: vi.fn(),
  retryAnalysis: vi.fn(),
  runAnalysisNow: vi.fn(),
  saveFeedback: vi.fn(),
  translateContent: vi.fn(),
}))

vi.mock('../api', () => apiMocks)

describe('内容详情翻译视图', () => {
  it('完成翻译后展示左右两个连续 Markdown 文档', async () => {
    apiMocks.getProfile.mockResolvedValue({ evaluation_mode: false })
    apiMocks.getContent.mockResolvedValue({
      id: 'content-1',
      title: 'English article',
      author: null,
      source_url: 'https://example.com/article',
      source_type: 'web',
      capture_quality: 'good',
      created_at: '2026-08-14T00:00:00Z',
      analysis_id: 'analysis-1',
      analysis_status: 'completed',
      one_sentence_summary: null,
      recommendation: null,
      ai_recommendation: null,
      user_recommendation: null,
      discovery_type: null,
      queue: {
        stage: 'completed',
        execution_mode: 'scheduled',
        waiting_for_schedule: false,
        next_eligible_at: null,
      },
      markdown: '# English title\n\nRead the guide.\n\n```python\nprint("ok")\n```',
      source_language: 'en',
      triage: null,
      content_analysis: null,
      personal_evaluation: null,
      feedback: null,
      translation: {
        id: 'translation-1',
        status: 'completed',
        source_language: 'en',
        target_language: 'zh-CN',
        completed_blocks: 2,
        total_blocks: 2,
        model: 'test-model',
        prompt_version: 'translation-v0.1',
        last_error: null,
        created_at: '2026-08-14T00:00:00Z',
        completed_at: '2026-08-14T00:01:00Z',
        blocks: [
          {
            id: 'b1',
            kind: 'heading',
            source_markdown: '# English title',
            translated_markdown: '# 中文标题',
            shared: false,
          },
          {
            id: 'b2',
            kind: 'paragraph',
            source_markdown: 'Read the guide.',
            translated_markdown: '阅读指南。',
            shared: false,
          },
          {
            id: 'b3',
            kind: 'code',
            source_markdown: '```python\nprint("ok")\n```',
            translated_markdown: null,
            shared: true,
          },
        ],
      },
    })

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/contents/:contentId', component: ContentDetailView }],
    })
    await router.push('/contents/content-1')
    await router.isReady()
    const wrapper = mount(ContentDetailView, {
      global: { plugins: [router, VueQueryPlugin] },
    })
    await flushPromises()

    expect(wrapper.findAll('button').some((button) => button.text() === '只看原文')).toBe(true)
    const documents = wrapper.findAll('.translation-document')
    expect(documents).toHaveLength(2)
    expect(wrapper.findAll('.translation-row')).toHaveLength(0)
    expect(documents[0].text()).toContain('English title')
    expect(documents[0].text()).not.toContain('中文标题')
    expect(documents[1].text()).toContain('中文标题')
    expect(documents[1].text()).toContain('阅读指南。')
    expect(documents[0].text()).toContain('print("ok")')
    expect(documents[1].text()).toContain('print("ok")')
    wrapper.unmount()
  })
})
