import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createI18n } from 'vue-i18n'

import TimelineEditorModal from '../TimelineEditorModal.vue'
import * as services from '@/services/knowledge-base'
import * as arco from '@arco-design/web-vue'

vi.mock('@/services/knowledge-base')
vi.mock('@arco-design/web-vue', () => ({
  Message: { success: vi.fn(), error: vi.fn() },
  Modal: { warning: vi.fn() },
  Drawer: { install: vi.fn() },
  Button: { install: vi.fn() },
  Empty: { install: vi.fn() },
  Input: { install: vi.fn() },
  Skeleton: { install: vi.fn() },
}))

const mocks = vi.mocked(services)

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      space: {
        datasets: {
          detail: {
            material: {
              reassembleTitle: '时间线编排',
              reassembleHint: '拖拽调整顺序',
              reassembleDelete: '删除',
              reassembleReplace: '替换',
              reassembleReplaceTitle: '选择替换素材',
              reassemblePickDoc: '选择素材',
              reassemblePickSegment: '选择段落',
              reassembleSubmit: '生成成片',
              reassembleCancel: '取消',
              reassembleBack: '返回',
              reassembleSubmitted: '已提交后台处理',
              reassembleFailed: '编排提交失败',
              reassembleEmpty: '暂无时间线段落',
              reassembleNamePlaceholder: '成品名称（可选）',
            },
          },
        },
      },
    },
  },
})

const props = { knowledgeBaseId: 'kb-1', documentId: 'doc-1', visible: true }

const stubs = {
  'a-modal': {
    template: '<div><slot name="title" /><slot /></div>',
    props: ['visible'],
  },
  'a-input': { template: '<input :value="modelValue" />', props: ['modelValue'] },
  'a-button': { template: '<button @click="$emit(\'click\')"><slot /></button>' },
  'a-empty': { template: '<div><slot name="description" /></div>' },
  'a-skeleton': { template: '<div />' },
}

const timelineSegments = [
  { id: 's1', position: 1, content: '第一段', source: 'vision_timeline', start_sec: 0, end_sec: 5, frame_url: 'https://cos/f1.jpg', speech_text: '台词一' },
  { id: 's2', position: 2, content: '第二段', source: 'vision_timeline', start_sec: 5, end_sec: 10, frame_url: 'https://cos/f2.jpg', speech_text: '台词二' },
  { id: 's3', position: 3, content: '第三段', source: 'vision_timeline', start_sec: 10, end_sec: 15, frame_url: 'https://cos/f3.jpg', speech_text: '台词三' },
]

const paginator = { current_page: 1, page_size: 20, total_page: 1, total_record: 1 }

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getKnowledgeSegmentsWithPage.mockResolvedValue({ data: { list: timelineSegments, paginator } })
  mocks.getKnowledgeDocumentsWithPage.mockResolvedValue({ data: { list: [], paginator } })
  mocks.reassembleKnowledgeDocument.mockResolvedValue({ data: { task_id: 't1' }, message: '', code: 'success' })
})

describe('TimelineEditorModal', () => {
  it('挂载后渲染主文档全部时间线段落', async () => {
    const wrapper = mount(TimelineEditorModal, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    expect(mocks.getKnowledgeSegmentsWithPage).toHaveBeenCalledWith('kb-1', 'doc-1', expect.anything())
    expect(wrapper.text()).toContain('第一段')
    expect(wrapper.text()).toContain('第二段')
    expect(wrapper.text()).toContain('第三段')
  })

  it('点击删除后段落减少，删光后提交按钮禁用', async () => {
    const wrapper = mount(TimelineEditorModal, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    const deleteButtons = wrapper.findAll('button[data-test="remove-clip"]')
    await deleteButtons[0].trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('第一段')
  })

  it('提交时携带 clips 与名称', async () => {
    const wrapper = mount(TimelineEditorModal, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    await wrapper.find('button[data-test="submit"]').trigger('click')
    await flushPromises()
    expect(mocks.reassembleKnowledgeDocument).toHaveBeenCalledWith('kb-1', 'doc-1', {
      clips: [
        { document_id: 'doc-1', segment_index: 1 },
        { document_id: 'doc-1', segment_index: 2 },
        { document_id: 'doc-1', segment_index: 3 },
      ],
      name: '',
    })
  })

  it('替换流程：选择素材 → 选择段落 → clip 更新为替换素材', async () => {
    mocks.getKnowledgeDocumentsWithPage.mockResolvedValue({
      data: {
        list: [
          { id: 'repl-1', name: '替换源.mp4', media_type: 'video', status: 'completed', character_count: 0 },
        ],
        paginator,
      },
    })
    mocks.getKnowledgeSegmentsWithPage.mockResolvedValueOnce({ data: { list: timelineSegments, paginator } }) // 主文档
      .mockResolvedValueOnce({
        data: {
          list: [
            { id: 'r1', position: 1, content: '替换段', source: 'vision_timeline', start_sec: 2, end_sec: 7, frame_url: '', speech_text: '替换台词' },
          ],
          paginator,
        },
      })
    const wrapper = mount(TimelineEditorModal, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()

    await wrapper.find('button[data-test="replace-clip-0"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('替换源.mp4')

    await wrapper.find('button[data-test="pick-doc-repl-1"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('替换段')

    await wrapper.find('button[data-test="pick-segment-0"]').trigger('click')
    await flushPromises()

    await wrapper.find('button[data-test="submit"]').trigger('click')
    await flushPromises()
    expect(mocks.reassembleKnowledgeDocument).toHaveBeenCalledWith('kb-1', 'doc-1', {
      clips: [
        { document_id: 'repl-1', segment_index: 1 },
        { document_id: 'doc-1', segment_index: 2 },
        { document_id: 'doc-1', segment_index: 3 },
      ],
      name: '',
    })
  })
})
