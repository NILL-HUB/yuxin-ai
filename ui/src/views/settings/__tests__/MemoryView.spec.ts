import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MemoryView from '@/views/settings/MemoryView.vue'

const mocks = vi.hoisted(() => ({
  getMemoryGraph: vi.fn(),
  getClusterSubgraph: vi.fn(),
  getMemoryDetail: vi.fn(),
  getMemoryDigest: vi.fn(),
  triggerConsolidation: vi.fn(),
  listSkills: vi.fn(),
  editMemory: vi.fn(),
  softDeleteMemory: vi.fn(),
  hardDeleteMemory: vi.fn(),
  decayMemory: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/memory-graph', () => ({
  getMemoryGraph: mocks.getMemoryGraph,
  getClusterSubgraph: mocks.getClusterSubgraph,
  getMemoryDetail: mocks.getMemoryDetail,
  getMemoryDigest: mocks.getMemoryDigest,
  triggerConsolidation: mocks.triggerConsolidation,
  listSkills: mocks.listSkills,
  editMemory: mocks.editMemory,
  softDeleteMemory: mocks.softDeleteMemory,
  hardDeleteMemory: mocks.hardDeleteMemory,
  decayMemory: mocks.decayMemory,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    success: mocks.messageSuccess,
    error: mocks.messageError,
    warning: vi.fn(),
  },
}))

vi.mock('@/stores/account', () => ({
  useAccountStore: () => ({
    account: { id: 'test-user-id' },
  }),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      const map: Record<string, string> = {
        'memory.graph.pageTitle': '记忆图谱',
        'memory.graph.pageDescription': '以图谱方式查看和管理你的记忆',
        'memory.graph.graphTab': '记忆图谱',
        'memory.graph.consolidateBtn': '执行巩固',
        'memory.graph.selectClusterHint': '点击上方分类查看记忆子图',
        'memory.graph.totalNodes': `共 ${params?.count ?? 0} 条记忆`,
        'memory.graph.lastUpdated': '最近更新',
        'memory.memoryType.profile': '个人资料',
        'memory.memoryType.preference': '偏好',
        'memory.memoryTypeDesc.profile': '用户的基本身份信息',
      }
      return map[key] ?? key
    },
  }),
}))

const slotStub = { template: '<div><slot /></div>' }
const buttonStub = {
  props: ['type', 'size', 'status', 'loading', 'disabled'],
  emits: ['click'],
  template:
    '<button type="button" :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>',
}

const renderView = async (graphData: any = null) => {
  mocks.getMemoryGraph.mockResolvedValue(
    graphData || {
      user_id: 'test-user-id',
      clusters: [
        { memory_type: 'profile', node_count: 5, last_updated_at: '2026-07-01T00:00:00Z' },
        { memory_type: 'preference', node_count: 3, last_updated_at: '2026-07-02T00:00:00Z' },
      ],
      total_nodes: 8,
    },
  )
  mocks.getClusterSubgraph.mockResolvedValue({ nodes: [], edges: [], truncated: false })
  mocks.getMemoryDetail.mockResolvedValue({ memory_id: '', content: '', related: [] })
  mocks.getMemoryDigest.mockResolvedValue({ user_id: 'test-user-id', digest: '', cached: false })
  mocks.triggerConsolidation.mockResolvedValue({
    user_id: 'test-user-id',
    success: true,
    total_items: 0,
    phase_results: {},
    errors: [],
    task_id: null,
  })
  mocks.listSkills.mockResolvedValue({ user_id: 'test-user-id', skills: [], total: 0 })

  const wrapper = mount(MemoryView, {
    global: {
      stubs: {
        'a-button': buttonStub,
        'a-tabs': slotStub,
        'a-tab-pane': slotStub,
        'a-spin': slotStub,
        'a-tag': slotStub,
        'a-modal': slotStub,
        'a-form': slotStub,
        'a-form-item': slotStub,
        'a-textarea': slotStub,
        'a-slider': slotStub,
        'a-popconfirm': slotStub,
        'icon-refresh': { template: '<i />' },
        'icon-bookmark': { template: '<i />' },
        'icon-bulb': { template: '<i />' },
        'icon-edit': { template: '<i />' },
        'icon-delete': { template: '<i />' },
        'icon-minus-circle': { template: '<i />' },
        MemoryClusterView: true,
        MemoryGraphView: true,
        MemoryNodeDetail: true,
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('MemoryView', () => {
  it('renders the page title', async () => {
    const wrapper = await renderView()
    expect(wrapper.text()).toContain('记忆图谱')
  })

  it('loads graph data on mount', async () => {
    await renderView()
    expect(mocks.getMemoryGraph).toHaveBeenCalledWith('test-user-id')
  })

  it('renders the consolidate button', async () => {
    const wrapper = await renderView()
    expect(wrapper.text()).toContain('执行巩固')
  })

  it('triggers consolidation on button click', async () => {
    const wrapper = await renderView()
    const btn = wrapper.find('[data-test="consolidate-btn"]')
    await btn.trigger('click')
    await flushPromises()
    expect(mocks.triggerConsolidation).toHaveBeenCalledWith('test-user-id')
    expect(mocks.messageSuccess).toHaveBeenCalled()
  })
})
