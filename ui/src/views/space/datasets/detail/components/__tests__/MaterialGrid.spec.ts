import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const mocks = vi.hoisted(() => ({ getKnowledgeDocumentsWithPage: vi.fn() }))
vi.mock('@/services/knowledge-base', () => ({
  getKnowledgeDocumentsWithPage: mocks.getKnowledgeDocumentsWithPage,
}))
vi.mock('@arco-design/web-vue', () => ({
  Message: { error: vi.fn() },
  Form: {},
  Modal: {},
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      space: {
        datasets: {
          detail: {
            material: {
              gridView: '网格',
              tableView: '表格',
              empty: '暂无素材',
              searchPlaceholder: '搜索素材',
            },
          },
        },
      },
    },
    'en-US': {
      space: {
        datasets: {
          detail: {
            material: {
              gridView: 'Grid',
              tableView: 'Table',
              empty: 'No materials',
              searchPlaceholder: 'Search materials',
            },
          },
        },
      },
    },
  },
})

const stubs = {
  'a-empty': { template: '<div><slot name="description" /></div>' },
  'a-input': { template: '<input />' },
}

import MaterialGrid from '@/views/space/datasets/detail/components/MaterialGrid.vue'

describe('MaterialGrid', () => {
  beforeEach(() => mocks.getKnowledgeDocumentsWithPage.mockReset())

  it('挂载后按当前分区拉取素材并以网格渲染', async () => {
    mocks.getKnowledgeDocumentsWithPage.mockResolvedValue({
      data: {
        list: [
          {
            id: 'd1',
            name: 'demo.mp4',
            media_type: 'video',
            status: 'completed',
            character_count: 120,
            created_at: 1700000000,
          },
        ],
        paginator: { current_page: 1, page_size: 20, total_page: 1, total_record: 1 },
      },
    })
    const wrapper = mount(MaterialGrid, {
      props: { knowledgeBaseId: 'kb-1', partitionId: '' },
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    expect(mocks.getKnowledgeDocumentsWithPage).toHaveBeenCalledWith(
      'kb-1',
      expect.objectContaining({ partition_id: undefined }),
    )
    expect(wrapper.text()).toContain('demo.mp4')
    expect(wrapper.text()).toContain('表格')
  })

  it('分区变化时重新拉取并携带 partition_id', async () => {
    mocks.getKnowledgeDocumentsWithPage.mockResolvedValue({
      data: { list: [], paginator: { current_page: 1, page_size: 20, total_page: 1, total_record: 0 } },
    })
    const wrapper = mount(MaterialGrid, {
      props: { knowledgeBaseId: 'kb-1', partitionId: '' },
      global: { plugins: [i18n], stubs },
    })
    await wrapper.setProps({ partitionId: 'p-key' })
    await flushPromises()
    expect(mocks.getKnowledgeDocumentsWithPage).toHaveBeenLastCalledWith(
      'kb-1',
      expect.objectContaining({ partition_id: 'p-key' }),
    )
  })
})