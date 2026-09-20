import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const mocks = vi.hoisted(() => ({ getPartitions: vi.fn() }))
vi.mock('@/services/knowledge-base', () => ({ getPartitions: mocks.getPartitions }))
vi.mock('@arco-design/web-vue', () => ({ Message: { error: vi.fn() } }))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': { space: { datasets: { detail: { partitions: { title: '分区导航', all: '全部素材' } } } } },
    'en-US': { space: { datasets: { detail: { partitions: { title: 'Partitions', all: 'All materials' } } } } },
  },
})

import PartitionTreeNav from '@/views/space/datasets/detail/components/PartitionTreeNav.vue'

describe('PartitionTreeNav', () => {
  beforeEach(() => mocks.getPartitions.mockReset())

  it('挂载后拉取分区树并渲染，含「全部素材」根节点', async () => {
    mocks.getPartitions.mockResolvedValue({
      data: [
        { id: 'p1', name: '2026-09', partition_key: '2026-09', parent_id: '', description: '', sort_order: 1 },
        { id: 'p1-1', name: 'Uploads', partition_key: '2026-09/uploads', parent_id: 'p1', description: '', sort_order: 1 },
      ],
    })
    const wrapper = mount(PartitionTreeNav, {
      props: { knowledgeBaseId: 'kb-1' },
      global: { plugins: [i18n] },
    })
    await flushPromises()
    expect(mocks.getPartitions).toHaveBeenCalledWith('kb-1')
    expect(wrapper.text()).toContain('全部素材')
    expect(wrapper.text()).toContain('2026-09')
  })

  it('点击根节点 emit select 事件与空分区 id', async () => {
    mocks.getPartitions.mockResolvedValue({ data: [] })
    const wrapper = mount(PartitionTreeNav, {
      props: { knowledgeBaseId: 'kb-1' },
      global: { plugins: [i18n] },
    })
    await flushPromises()
    await wrapper.find('[data-test="nav-all"]').trigger('click')
    const emitted = wrapper.emitted('select')
    expect(emitted).toBeTruthy()
    expect(emitted![0][0]).toBe('')
  })

  it('点击分区节点 emit select 事件与分区 UUID', async () => {
    mocks.getPartitions.mockResolvedValue({
      data: [{ id: 'p1', name: '2026-09', partition_key: '2026-09', parent_id: '', description: '', sort_order: 1 }],
    })
    const wrapper = mount(PartitionTreeNav, {
      props: { knowledgeBaseId: 'kb-1' },
      global: { plugins: [i18n] },
    })
    await flushPromises()
    await wrapper.find('[data-test="nav-partition-p1"]').trigger('click')
    expect(wrapper.emitted('select')![0][0]).toBe('p1')
  })
})