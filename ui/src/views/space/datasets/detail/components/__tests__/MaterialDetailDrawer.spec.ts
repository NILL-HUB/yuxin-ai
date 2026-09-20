import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const mocks = vi.hoisted(() => ({
  getKnowledgeDocument: vi.fn(),
  getKnowledgeSegmentsWithPage: vi.fn(),
  triggerDocumentL2: vi.fn(),
  deleteKnowledgeDocument: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
}))
vi.mock('@/services/knowledge-base', () => ({
  getKnowledgeDocument: mocks.getKnowledgeDocument,
  getKnowledgeSegmentsWithPage: mocks.getKnowledgeSegmentsWithPage,
  triggerDocumentL2: mocks.triggerDocumentL2,
  deleteKnowledgeDocument: mocks.deleteKnowledgeDocument,
}))
vi.mock('@arco-design/web-vue', () => ({
  Message: { success: mocks.messageSuccess, error: mocks.messageError },
  Modal: {},
  Form: {},
}))

const material = {
  status: '状态',
  segmentCount: '分段数',
  characterCount: '字符数',
  triggerL2: 'L2 深度解析',
  noSegments: '暂无分段',
  delete: '删除素材',
  reassemble: '重新编排',
  reassembleTitle: '时间线编排',
  reassembleHint: '拖拽调整顺序，可删除段落或用其他素材的段落替换',
  reassembleDelete: '删除',
  reassembleReplace: '替换',
  reassembleReplaceTitle: '选择替换素材',
  reassemblePickDoc: '选择素材',
  reassemblePickSegment: '选择段落',
  reassembleSubmit: '生成成片',
  reassembleCancel: '取消',
  reassembleBack: '返回',
  reassembleSubmitted: '已提交后台处理，完成后会自动存入成品库',
  reassembleFailed: '编排提交失败，请稍后重试',
  reassembleEmpty: '暂无时间线段落，无法编排',
  reassembleNamePlaceholder: '成品名称（可选）',
}
const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': { space: { datasets: { detail: { material } } } },
    'en-US': { space: { datasets: { detail: { material: { ...material } } } } },
  },
})

const stubs = {
  'a-drawer': { template: '<div><slot name="title" /><slot /></div>' },
  'a-button': { template: '<button type="button"><slot /></button>' },
  'a-tag': { template: '<span><slot /></span>' },
  'a-empty': { template: '<div><slot name="description" /></div>' },
  'a-skeleton': { template: '<div />' },
  'timeline-editor-modal': {
    template: '<div v-if="visible" data-test="reassemble-modal" />',
    props: ['visible'],
  },
}

import MaterialDetailDrawer from '@/views/space/datasets/detail/components/MaterialDetailDrawer.vue'

const props = { knowledgeBaseId: 'kb-1', documentId: 'd1', visible: true }

describe('MaterialDetailDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.getKnowledgeDocument.mockResolvedValue({
      data: { id: 'd1', name: 'demo.mp4', segment_count: 3, character_count: 500, status: 'completed' },
    })
    mocks.getKnowledgeSegmentsWithPage.mockResolvedValue({
      data: {
        list: [{ id: 's1', position: 1, content: 'some segment content' }],
        paginator: { current_page: 1, page_size: 20, total_page: 1, total_record: 1 },
      },
    })
    mocks.triggerDocumentL2.mockResolvedValue({ code: 'success', message: 'ok', data: {} })
    mocks.deleteKnowledgeDocument.mockResolvedValue({ code: 'success', message: 'ok', data: {} })
  })

  it('打开时拉取文档详情与分段，渲染基本信息和分段内容', async () => {
    const wrapper = mount(MaterialDetailDrawer, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    expect(mocks.getKnowledgeDocument).toHaveBeenCalledWith('kb-1', 'd1')
    expect(mocks.getKnowledgeSegmentsWithPage).toHaveBeenCalled()
    expect(wrapper.text()).toContain('demo.mp4')
    expect(wrapper.text()).toContain('some segment content')
  })

  it('点击 L2 深度解析调用 triggerDocumentL2 并复位 loading', async () => {
    const wrapper = mount(MaterialDetailDrawer, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    const l2Button = wrapper.findAll('button').find((b) => b.text().includes('L2 深度解析'))
    expect(l2Button).toBeTruthy()
    await l2Button!.trigger('click')
    expect(mocks.triggerDocumentL2).toHaveBeenCalledWith('kb-1', 'd1')
    await flushPromises()
    expect(mocks.messageSuccess).toHaveBeenCalled()
  })

  it('点击删除调用 deleteKnowledgeDocument 并 emit deleted', async () => {
    const wrapper = mount(MaterialDetailDrawer, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    const deleteButton = wrapper.findAll('button').find((b) => b.text().includes('删除素材'))
    expect(deleteButton).toBeTruthy()
    await deleteButton!.trigger('click')
    expect(mocks.deleteKnowledgeDocument).toHaveBeenCalledWith('kb-1', 'd1')
    expect(wrapper.emitted('deleted')).toBeTruthy()
  })

  it('视频成品带 playback_url 时渲染内联播放器', async () => {
    mocks.getKnowledgeDocument.mockResolvedValue({
      data: {
        id: 'd1',
        name: 'demo.mp4',
        media_type: 'video',
        playback_url: 'https://cos/out.mp4',
        segment_count: 0,
        character_count: 0,
        status: 'completed',
      },
    })
    const wrapper = mount(MaterialDetailDrawer, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    expect(wrapper.find('video').attributes('src')).toBe('https://cos/out.mp4')
  })

  it('分段带 frame_url 时渲染帧缩略图与时间标签', async () => {
    mocks.getKnowledgeSegmentsWithPage.mockResolvedValue({
      data: {
        list: [
          {
            id: 's1',
            position: 1,
            content: 'some segment content',
            frame_url: 'https://cos/f.jpg',
            start_sec: 3.2,
            end_sec: 8.7,
          },
        ],
        paginator: { current_page: 1, page_size: 20, total_page: 1, total_record: 1 },
      },
    })
    const wrapper = mount(MaterialDetailDrawer, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    expect(wrapper.find('img').attributes('src')).toBe('https://cos/f.jpg')
    expect(wrapper.text()).toContain('00:03')
  })

  it('视频素材显示重新编排按钮，点击后打开编排弹窗', async () => {
    mocks.getKnowledgeDocument.mockResolvedValue({
      data: {
        id: 'd1',
        name: 'demo.mp4',
        media_type: 'video',
        segment_count: 3,
        character_count: 0,
        status: 'completed',
      },
    })
    mocks.getKnowledgeSegmentsWithPage.mockResolvedValue({
      data: {
        list: [
          { id: 's1', position: 1, content: '段1', source: 'vision_timeline', start_sec: 0, end_sec: 5 },
        ],
        paginator: { current_page: 1, page_size: 20, total_page: 1, total_record: 1 },
      },
    })
    const wrapper = mount(MaterialDetailDrawer, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    const button = wrapper.find('[data-test="open-reassemble"]')
    expect(button.exists()).toBe(true)
    await button.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="reassemble-modal"]').exists()).toBe(true)
  })
})