import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({ getKnowledgeBase: vi.fn() }))
vi.mock('@/services/knowledge-base', () => ({ getKnowledgeBase: mocks.getKnowledgeBase }))
vi.mock('@arco-design/web-vue', () => ({
  Message: { success: vi.fn(), error: vi.fn() },
  Modal: {},
  Form: {},
}))
vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRoute: () => ({ params: { dataset_id: 'kb-1' } }),
    RouterLink: { template: '<a><slot /></a>' },
  }
})
vi.mock('@/views/space/datasets/detail/components/UsagePanel.vue', () => ({
  default: { name: 'UsagePanelStub', template: '<div class="usage-stub">usage</div>' },
}))
vi.mock('@/views/space/datasets/detail/components/PartitionTreeNav.vue', () => ({
  default: {
    name: 'PartitionTreeNavStub',
    props: ['knowledgeBaseId'],
    template:
      '<button type="button" data-test="nav-stub" @click="$emit(\'select\', \'p-key\')">nav</button>',
  },
}))
vi.mock('@/views/space/datasets/detail/components/MaterialGrid.vue', () => ({
  default: {
    name: 'MaterialGridStub',
    props: ['knowledgeBaseId', 'partitionId'],
    template: '<div data-test="grid-stub" :data-partition-id="partitionId" />',
  },
}))
vi.mock('@/views/space/datasets/detail/components/MaterialDetailDrawer.vue', () => ({
  default: { name: 'MaterialDetailDrawerStub', template: '<div class="drawer-stub" />' },
}))

import IndexView from '@/views/space/datasets/detail/IndexView.vue'

describe('IndexView', () => {
  beforeEach(() => {
    mocks.getKnowledgeBase.mockReset()
    mocks.getKnowledgeBase.mockResolvedValue({
      data: { id: 'kb-1', name: '素材库', icon: '', description: '' },
    })
  })

  it('渲染板块名、用量面板、分区树与素材网格', async () => {
    const wrapper = mount(IndexView, { global: { stubs: { 'a-button': { template: '<button type="button"><slot /></button>' } } } })
    await flushPromises()
    expect(mocks.getKnowledgeBase).toHaveBeenCalledWith('kb-1')
    expect(wrapper.text()).toContain('素材库')
    expect(wrapper.find('.usage-stub').exists()).toBe(true)
    expect(wrapper.find('[data-test="nav-stub"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="grid-stub"]').exists()).toBe(true)
    expect(wrapper.find('.drawer-stub').exists()).toBe(true)
  })

  it('点击分区树节点联动更新素材网格 partition-id', async () => {
    const wrapper = mount(IndexView, { global: { stubs: { 'a-button': { template: '<button type="button"><slot /></button>' } } } })
    await flushPromises()
    expect(wrapper.find('[data-test="grid-stub"]').attributes('data-partition-id')).toBe('')
    await wrapper.find('[data-test="nav-stub"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="grid-stub"]').attributes('data-partition-id')).toBe('p-key')
  })
})