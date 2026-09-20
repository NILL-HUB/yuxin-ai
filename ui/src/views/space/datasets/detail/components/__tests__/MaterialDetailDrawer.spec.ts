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
})