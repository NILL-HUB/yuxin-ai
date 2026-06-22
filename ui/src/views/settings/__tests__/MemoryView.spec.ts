import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MemoryView from '@/views/settings/MemoryView.vue'

const mocks = vi.hoisted(() => ({
  listUserMemories: vi.fn(),
  listMemoryCandidates: vi.fn(),
  createUserMemory: vi.fn(),
  updateUserMemory: vi.fn(),
  deleteUserMemory: vi.fn(),
  confirmMemoryCandidate: vi.fn(),
  ignoreMemoryCandidate: vi.fn(),
  getUserMemory: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
  messageWarning: vi.fn(),
}))

vi.mock('@/services/user-memory', () => ({
  listUserMemories: mocks.listUserMemories,
  listMemoryCandidates: mocks.listMemoryCandidates,
  createUserMemory: mocks.createUserMemory,
  updateUserMemory: mocks.updateUserMemory,
  deleteUserMemory: mocks.deleteUserMemory,
  confirmMemoryCandidate: mocks.confirmMemoryCandidate,
  ignoreMemoryCandidate: mocks.ignoreMemoryCandidate,
  getUserMemory: mocks.getUserMemory,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    success: mocks.messageSuccess,
    error: mocks.messageError,
    warning: mocks.messageWarning,
  },
}))

const slotStub = { template: '<div><slot /></div>' }

const buttonStub = {
  props: ['type', 'size', 'status', 'loading', 'disabled'],
  emits: ['click'],
  template:
    '<button type="button" :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>',
}

const modalStub = {
  props: { visible: Boolean, title: String, okText: String, cancelText: String, okLoading: Boolean },
  emits: ['update:visible', 'ok', 'cancel'],
  template: '<div v-if="visible" class="modal-stub"><slot /></div>',
}

const formItemStub = {
  props: ['label'],
  template: '<div class="form-item"><label>{{ label }}</label><slot /></div>',
}

const tableStub = {
  props: { data: { type: Array, default: () => [] }, loading: Boolean },
  template:
    '<div class="table-stub"><div v-for="item in data" :key="item.id" :data-memory-type="item.memory_type" class="memory-row">{{ item.memory_type }}</div></div>',
}

const renderView = async (memories: any[] = [], candidates: any[] = []) => {
  mocks.listUserMemories.mockResolvedValue(memories)
  mocks.listMemoryCandidates.mockResolvedValue(candidates)
  const wrapper = mount(MemoryView, {
    global: {
      stubs: {
        'a-button': buttonStub,
        'a-modal': modalStub,
        'a-form': slotStub,
        'a-form-item': formItemStub,
        'a-select': slotStub,
        'a-textarea': slotStub,
        'a-slider': slotStub,
        'a-input': slotStub,
        'a-tag': slotStub,
        'a-switch': slotStub,
        'a-table': tableStub,
        'a-table-column': slotStub,
        'a-tabs': slotStub,
        'a-tab-pane': slotStub,
        'a-spin': slotStub,
        'a-space': slotStub,
        'a-popconfirm': slotStub,
        'icon-plus': { template: '<i />' },
        'icon-search': { template: '<i />' },
        'icon-bookmark': { template: '<i />' },
        'icon-bulb': { template: '<i />' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('MemoryView', () => {
  it('renders the page title', async () => {
    const wrapper = await renderView()

    expect(wrapper.text()).toContain('长期记忆管理')
  })

  it('opens the create memory modal', async () => {
    const wrapper = await renderView()

    expect(wrapper.text()).not.toContain('记忆类型')

    await wrapper.find('[data-test="create-memory-btn"]').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('记忆类型')
    expect(wrapper.text()).toContain('记忆内容')
    expect(wrapper.text()).toContain('置信度')
  })

  it('renders memory type tags', async () => {
    const wrapper = await renderView([
      {
        id: 'm1',
        memory_type: 'preference',
        content: '偏好深色主题',
        confidence: 4,
        status: 'active',
        created_from: 'manual_input',
        created_at: '2025-01-01T00:00:00Z',
      },
    ])

    expect(wrapper.find('[data-memory-type="preference"]').exists()).toBe(true)
  })

  it('shows the empty state when no memories', async () => {
    const wrapper = await renderView([])

    expect(wrapper.text()).toContain('暂无已保存的记忆')
  })
})
