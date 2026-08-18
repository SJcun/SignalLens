import { VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'

import ContentDetailView from './ContentDetailView.vue'
import type { ContentDetail } from '../api'

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
      delta_summary: null,
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
      section_index: null,
      guided_flow_available: false,
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

function guidedFlowDetail(): ContentDetail {
  return {
    id: 'content-guided',
    title: '引导流测试文章',
    author: null,
    source_url: 'https://example.com/guided',
    source_type: 'web',
    capture_quality: 'good',
    created_at: '2026-08-14T00:00:00Z',
    analysis_id: 'analysis-guided',
    delta_summary: null,
    analysis_status: 'completed',
    one_sentence_summary: '文章摘要。',
    recommendation: 'selective_read',
    ai_recommendation: 'selective_read',
    user_recommendation: null,
    discovery_type: 'adjacent',
    queue: {
      stage: 'completed',
      execution_mode: 'scheduled',
      waiting_for_schedule: false,
      next_eligible_at: null,
    },
    markdown: '# 引导流测试文章\n\n导语内容。\n\n## 第一章\n\n第一章正文。\n\n## 第二章\n\n第二章正文。\n\n## 第三章\n\n第三章正文。',
    source_language: 'zh-CN',
    translation: null,
    triage: null,
    content_analysis: {
      one_sentence_summary: '文章摘要。',
      summary: '整体摘要。',
      content_map: [
        { section_ref: 'sec-001', title: '第一章', summary: '第一章摘要。' },
        { section_ref: 'sec-002', title: '第二章', summary: '第二章摘要。' },
        { section_ref: 'sec-003', title: '第三章', summary: '第三章摘要。' },
      ],
      key_points: [],
      claims: [],
      counterarguments: [],
      limitations: [],
      unresolved_questions: [],
      unverified_claims: [],
    },
    personal_evaluation: {
      relevance: 'medium',
      knowledge_overlap: 'low',
      known_or_redundant: false,
      novel_information: [],
      exploration_value: 'medium',
      perspective_diversity: 'medium',
      discovery_type: 'adjacent',
      recommendation: 'selective_read',
      recommendation_reason: '部分章节值得亲自阅读。',
      why_outside_profile: null,
      reading_plan: [
        { section_ref: 'sec-001', section: '第一章', action: 'skip', reason: '背景介绍可跳过。' },
        { section_ref: 'sec-002', section: '第二章', action: 'skim', reason: '只需了解结论。' },
        { section_ref: 'sec-003', section: '第三章', action: 'deep_read', reason: '关键论证需要精读。' },
      ],
    },
    feedback: null,
    section_index: {
      primary_heading_level: 2,
      sections: [
        { section_ref: 'sec-001', level: 2, title: '第一章', order: 1, start_line: 4, end_line: 8 },
        { section_ref: 'sec-002', level: 2, title: '第二章', order: 2, start_line: 8, end_line: 12 },
        { section_ref: 'sec-003', level: 2, title: '第三章', order: 3, start_line: 12, end_line: 15 },
      ],
    },
    guided_flow_available: true,
    claims: null,
    cognitive_delta: null,
    retrieval_context_status: null,
  }
}

async function mountGuidedFlow(detail: unknown) {
  apiMocks.getProfile.mockResolvedValue({ evaluation_mode: false })
  apiMocks.getContent.mockResolvedValue(detail)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/contents/:contentId', component: ContentDetailView }],
  })
  await router.push('/contents/content-guided')
  await router.isReady()
  const wrapper = mount(ContentDetailView, {
    global: { plugins: [router, VueQueryPlugin] },
  })
  await flushPromises()
  return wrapper
}

describe('内容详情引导阅读流', () => {
  it('满足条件时默认按原文顺序原位渲染折叠、摘要与原文', async () => {
    const wrapper = await mountGuidedFlow(guidedFlowDetail())

    // 顶部总览展示动作数量与模式切换，不承担目录跳转。
    const overview = wrapper.find('.guided-overview')
    expect(overview.text()).toContain('1 节重点精读')
    expect(overview.text()).toContain('1 节浏览摘要')
    expect(overview.text()).toContain('1 节跳过')
    expect(overview.text()).toContain('完整原文')

    // 上下文块（文章标题与导语）完整展示。
    expect(wrapper.find('.guided-context').text()).toContain('导语内容')

    // skip 章节原位折叠：只显示标题、跳过徽章与原因，不显示正文。
    const sections = wrapper.findAll('.guided-section')
    expect(sections).toHaveLength(3)
    expect(sections[0].text()).toContain('第一章')
    expect(sections[0].text()).toContain('跳过')
    expect(sections[0].text()).toContain('背景介绍可跳过。')
    expect(sections[0].text()).not.toContain('第一章正文')

    // skim 章节显示摘要与原因，原文折叠。
    expect(sections[1].text()).toContain('第二章摘要。')
    expect(sections[1].text()).toContain('只需了解结论。')
    expect(sections[1].text()).not.toContain('第二章正文')

    // deep_read 章节完整展示原文与精读标记。
    expect(sections[2].text()).toContain('精读')
    expect(sections[2].text()).toContain('第三章正文')

    // 章节保持来源顺序：第一章在前，第三章在后。
    expect(sections[0].text()).toContain('第一章')
    expect(sections[2].text()).toContain('第三章')
    wrapper.unmount()
  })

  it('折叠章节可在原位置展开，且保持本次会话的展开状态', async () => {
    const wrapper = await mountGuidedFlow(guidedFlowDetail())

    const skipSection = wrapper.findAll('.guided-section')[0]
    expect(skipSection.text()).not.toContain('第一章正文')
    await skipSection.find('button.guided-expand').trigger('click')
    expect(skipSection.text()).toContain('第一章正文')
    expect(skipSection.find('button.guided-expand').text()).toBe('收起原文')

    // 切到完整原文再切回，手动展开状态仍然保留。
    await wrapper.find('.guided-overview .view-toggle').trigger('click')
    expect(wrapper.find('.guided-flow .markdown-body').text()).toContain('第三章正文')
    await wrapper.find('.guided-overview .view-toggle').trigger('click')
    expect(wrapper.findAll('.guided-section')[0].text()).toContain('第一章正文')
    wrapper.unmount()
  })

  it('引导流不可用时退回完整原文，不显示引导入口', async () => {
    const detail = guidedFlowDetail()
    detail.guided_flow_available = false
    detail.section_index = null
    const wrapper = await mountGuidedFlow(detail)

    expect(wrapper.find('.guided-overview').exists()).toBe(false)
    const body = wrapper.find('.markdown-body')
    expect(body.text()).toContain('第一章正文')
    expect(body.text()).toContain('第三章正文')
    wrapper.unmount()
  })
})

/** 英文引导流文章：正文、章节行号与译文块行号一一对应。 */
function guidedEnglishFlowDetail(): ContentDetail {
  return {
    id: 'content-guided-en',
    title: 'Guided Flow Article',
    author: null,
    source_url: 'https://example.com/guided-en',
    source_type: 'web',
    capture_quality: 'good',
    created_at: '2026-08-14T00:00:00Z',
    analysis_id: 'analysis-guided-en',
    delta_summary: null,
    analysis_status: 'completed',
    one_sentence_summary: '文章摘要。',
    recommendation: 'selective_read',
    ai_recommendation: 'selective_read',
    user_recommendation: null,
    discovery_type: 'adjacent',
    queue: {
      stage: 'completed',
      execution_mode: 'scheduled',
      waiting_for_schedule: false,
      next_eligible_at: null,
    },
    markdown: [
      '# Guided Flow Article',
      '',
      'Intro text.',
      '',
      '## First Chapter',
      '',
      'First chapter body.',
      '',
      '## Second Chapter',
      '',
      'Second chapter body.',
      '',
      '## Third Chapter',
      '',
      'Third chapter body.',
    ].join('\n'),
    source_language: 'en',
    translation: {
      id: 'translation-guided-en',
      status: 'completed',
      source_language: 'en',
      target_language: 'zh-CN',
      completed_blocks: 8,
      total_blocks: 8,
      model: 'test-model',
      prompt_version: 'translation-v0.1',
      last_error: null,
      created_at: '2026-08-14T00:00:00Z',
      completed_at: '2026-08-14T00:01:00Z',
      blocks: [
        {
          id: 'b1',
          kind: 'heading',
          source_markdown: '# Guided Flow Article',
          translated_markdown: '# 引导流测试文章',
          shared: false,
          start_line: 0,
          end_line: 1,
        },
        {
          id: 'b2',
          kind: 'paragraph',
          source_markdown: 'Intro text.',
          translated_markdown: '导语译文。',
          shared: false,
          start_line: 2,
          end_line: 3,
        },
        {
          id: 'b3',
          kind: 'heading',
          source_markdown: '## First Chapter',
          translated_markdown: '## 第一章',
          shared: false,
          start_line: 4,
          end_line: 5,
        },
        {
          id: 'b4',
          kind: 'paragraph',
          source_markdown: 'First chapter body.',
          translated_markdown: '第一章正文译文。',
          shared: false,
          start_line: 6,
          end_line: 7,
        },
        {
          id: 'b5',
          kind: 'heading',
          source_markdown: '## Second Chapter',
          translated_markdown: '## 第二章',
          shared: false,
          start_line: 8,
          end_line: 9,
        },
        {
          id: 'b6',
          kind: 'paragraph',
          source_markdown: 'Second chapter body.',
          translated_markdown: '第二章正文译文。',
          shared: false,
          start_line: 10,
          end_line: 11,
        },
        {
          id: 'b7',
          kind: 'heading',
          source_markdown: '## Third Chapter',
          translated_markdown: '## 第三章',
          shared: false,
          start_line: 12,
          end_line: 13,
        },
        {
          id: 'b8',
          kind: 'paragraph',
          source_markdown: 'Third chapter body.',
          translated_markdown: '第三章正文译文。',
          shared: false,
          start_line: 14,
          end_line: 15,
        },
      ],
    },
    triage: null,
    content_analysis: {
      one_sentence_summary: '文章摘要。',
      summary: '整体摘要。',
      content_map: [
        { section_ref: 'sec-001', title: '第一章', summary: '第一章摘要。' },
        { section_ref: 'sec-002', title: '第二章', summary: '第二章摘要。' },
        { section_ref: 'sec-003', title: '第三章', summary: '第三章摘要。' },
      ],
      key_points: [],
      claims: [],
      counterarguments: [],
      limitations: [],
      unresolved_questions: [],
      unverified_claims: [],
    },
    personal_evaluation: {
      relevance: 'medium',
      knowledge_overlap: 'low',
      known_or_redundant: false,
      novel_information: [],
      exploration_value: 'medium',
      perspective_diversity: 'medium',
      discovery_type: 'adjacent',
      recommendation: 'selective_read',
      recommendation_reason: '部分章节值得亲自阅读。',
      why_outside_profile: null,
      reading_plan: [
        { section_ref: 'sec-001', section: '第一章', action: 'skip', reason: '背景介绍可跳过。' },
        { section_ref: 'sec-002', section: '第二章', action: 'skim', reason: '只需了解结论。' },
        { section_ref: 'sec-003', section: '第三章', action: 'deep_read', reason: '关键论证需要精读。' },
      ],
    },
    feedback: null,
    section_index: {
      primary_heading_level: 2,
      sections: [
        { section_ref: 'sec-001', level: 2, title: 'First Chapter', order: 1, start_line: 4, end_line: 8 },
        { section_ref: 'sec-002', level: 2, title: 'Second Chapter', order: 2, start_line: 8, end_line: 12 },
        { section_ref: 'sec-003', level: 2, title: 'Third Chapter', order: 3, start_line: 12, end_line: 15 },
      ],
    },
    guided_flow_available: true,
    claims: null,
    cognitive_delta: null,
    retrieval_context_status: null,
  }
}

describe('内容详情引导流与译文共存', () => {
  it('翻译完成后保留原文引导流，不自动切换对照视图', async () => {
    const wrapper = await mountGuidedFlow(guidedEnglishFlowDetail())

    // 没有自动切到双文档对照视图，按钮保留"中英对照"入口。
    expect(wrapper.findAll('.translation-document')).toHaveLength(0)
    expect(
      wrapper.findAll('button').some((button) => button.text() === '中英对照'),
    ).toBe(true)

    // 上下文块与章节正文保持原文，选择性阅读折叠行为不变。
    expect(wrapper.find('.guided-context').text()).toContain('Intro text.')
    expect(wrapper.find('.guided-context').text()).not.toContain('导语译文。')
    const sections = wrapper.findAll('.guided-section')
    expect(sections).toHaveLength(3)
    expect(sections[0].text()).toContain('First Chapter')
    expect(sections[0].text()).toContain('跳过')
    expect(sections[0].text()).toContain('背景介绍可跳过。')
    expect(sections[0].text()).not.toContain('First chapter body.')

    // skip 章节展开后展示原文。
    await sections[0].find('button.guided-expand').trigger('click')
    expect(sections[0].text()).toContain('First chapter body.')

    // deep_read 章节原位展示原文。
    expect(sections[2].text()).toContain('精读')
    expect(sections[2].text()).toContain('Third chapter body.')
    expect(sections[2].text()).not.toContain('第三章正文译文。')
    wrapper.unmount()
  })

  it('中英对照视图左右两侧都按章节标注选择性阅读动作', async () => {
    const wrapper = await mountGuidedFlow(guidedEnglishFlowDetail())

    const toggleButton = wrapper.findAll('button').find((button) => button.text() === '中英对照')
    expect(toggleButton).toBeDefined()
    await toggleButton!.trigger('click')

    const documents = wrapper.findAll('.translation-document')
    expect(documents).toHaveLength(2)

    // 左侧原文按章节标注：徽章、原文标题与正文都在。
    const sourceSections = documents[0].findAll('.guided-section')
    expect(sourceSections).toHaveLength(3)
    expect(
      sourceSections.map((section) => section.find('.guided-action-badge').text()),
    ).toEqual(['跳过', '浏览', '精读'])
    expect(sourceSections[0].text()).toContain('First Chapter')
    expect(sourceSections[0].text()).toContain('First chapter body.')
    expect(sourceSections[0].text()).not.toContain('第一章正文译文。')

    // 右侧译文同样按章节标注：徽章、译文标题与译文正文都在。
    const translatedSections = documents[1].findAll('.guided-section')
    expect(translatedSections).toHaveLength(3)
    expect(
      translatedSections.map((section) => section.find('.guided-action-badge').text()),
    ).toEqual(['跳过', '浏览', '精读'])
    expect(translatedSections[0].text()).toContain('第一章')
    expect(translatedSections[0].text()).toContain('第一章正文译文。')
    expect(translatedSections[0].text()).not.toContain('First chapter body.')

    // 两侧上下文的导语也各自保持原文与译文。
    expect(documents[0].find('.guided-context').text()).toContain('Intro text.')
    expect(documents[1].find('.guided-context').text()).toContain('导语译文。')

    const backButton = wrapper.findAll('button').find((button) => button.text() === '只看原文')
    expect(backButton).toBeDefined()
    await backButton!.trigger('click')

    // 返回后仍是原文引导流。
    const sections = wrapper.findAll('.guided-section')
    expect(sections).toHaveLength(3)
    expect(sections[0].text()).toContain('First Chapter')
    expect(sections[2].text()).toContain('Third chapter body.')
    wrapper.unmount()
  })

  it('译文块缺少行号时对照视图退回普通双文档，不做章节标注', async () => {
    const detail = guidedEnglishFlowDetail()
    detail.translation!.blocks = detail.translation!.blocks.map((block) => ({
      ...block,
      start_line: null,
      end_line: null,
    }))
    const wrapper = await mountGuidedFlow(detail)

    // 引导流保持原文，不自动切到对照视图。
    expect(wrapper.findAll('.translation-document')).toHaveLength(0)
    const sections = wrapper.findAll('.guided-section')
    expect(sections[2].text()).toContain('Third chapter body.')
    expect(sections[2].text()).not.toContain('第三章正文译文。')

    // 对照视图仍可用，但退化为左右两个连续文档，无章节徽章。
    const toggleButton = wrapper.findAll('button').find((button) => button.text() === '中英对照')
    await toggleButton!.trigger('click')
    const documents = wrapper.findAll('.translation-document')
    expect(documents).toHaveLength(2)
    expect(documents[0].findAll('.guided-section')).toHaveLength(0)
    expect(documents[1].findAll('.guided-section')).toHaveLength(0)
    expect(documents[0].text()).toContain('Third chapter body.')
    expect(documents[1].text()).toContain('第三章正文译文。')
    wrapper.unmount()
  })
})
