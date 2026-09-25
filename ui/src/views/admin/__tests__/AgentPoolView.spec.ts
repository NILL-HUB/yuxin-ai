import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAdminStore } from '@/stores/admin'
import AgentPoolView from '@/views/admin/AgentPoolView.vue'

const mocks = vi.hoisted(() => ({
  listAgentPoolConfigs: vi.fn(),
  createAgentPoolConfig: vi.fn(),
  updateAgentPoolConfig: vi.fn(),
  deleteAgentPoolConfig: vi.fn(),
  getAgentPoolStats: vi.fn(),
  checkAgentHealth: vi.fn(),
  setAgentPoolStatus: vi.fn(),
  listAdminApps: vi.fn(),
  updateAdminAppMetadata: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
  messageWarning: vi.fn(),
  modalWarning: vi.fn(),
}))

vi.mock('@/services/admin-agent-pool', () => ({
  listAgentPoolConfigs: mocks.listAgentPoolConfigs,
  createAgentPoolConfig: mocks.createAgentPoolConfig,
  updateAgentPoolConfig: mocks.updateAgentPoolConfig,
  deleteAgentPoolConfig: mocks.deleteAgentPoolConfig,
  getAgentPoolStats: mocks.getAgentPoolStats,
  checkAgentHealth: mocks.checkAgentHealth,
  setAgentPoolStatus: mocks.setAgentPoolStatus,
}))

vi.mock('@/services/admin-apps', () => ({
  listAdminApps: mocks.listAdminApps,
  updateAdminAppMetadata: mocks.updateAdminAppMetadata,
}))

vi.mock('@arco-design/web-vue', async () => {
  const actual = await vi.importActual<typeof import('@arco-design/web-vue')>('@arco-design/web-vue')
  return {
    ...actual,
    Message: {
      success: mocks.messageSuccess,
      error: mocks.messageError,
      warning: mocks.messageWarning,
    },
    Modal: { warning: mocks.modalWarning },
  }
})

const buttonStub = {
  props: ['type', 'status', 'loading', 'disabled'],
  emits: ['click'],
  template:
    '<button type="button" :disabled="loading || disabled" @click="$emit(\'click\')"><slot /></button>',
}

const selectStub = {
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue'],
  template:
    '<select :value="modelValue" :disabled="disabled" class="select-stub" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>',
}

const inputNumberStub = {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template:
    '<input type="number" :value="modelValue" @input="$emit(\'update:modelValue\', Number($event.target.value))" />',
}

const switchStub = {
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue'],
  template:
    '<input type="checkbox" :checked="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.checked)" />',
}

const modalStub = {
  props: ['visible', 'okLoading'],
  emits: ['ok', 'update:visible'],
  template:
    '<div v-if="visible" class="modal-stub"><slot /><button class="modal-ok" @click="$emit(\'ok\')">OK</button></div>',
}

const renderView = async (permissions = ['agent_pool:manage', 'app:read', 'app:update']) => {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAdminStore(pinia).update({
    id: 'admin-1',
    username: 'admin',
    email: 'admin@example.com',
    name: 'Admin',
    avatar: '',
    status: 'active',
    roles: ['operator'],
    permissions,
  })

  mocks.listAgentPoolConfigs.mockResolvedValue({
    code: 0,
    message: '',
    data: {
      list: [
        {
          id: 'cfg-1',
          app_id: 'app-1',
          enabled: true,
          health_status: 'healthy',
          metadata: {
            cost_level: 'medium',
            capabilities: ['coding'],
            task_types: ['qa'],
          },
        },
      ],
      paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 },
    },
  })
  mocks.getAgentPoolStats.mockResolvedValue({
    code: 0,
    message: '',
    data: { list: [{ total: 1, enabled: 1, healthy: 1 }] },
  })
  mocks.listAdminApps.mockResolvedValue({
    list: [
      {
        id: 'app-1',
        name: '编程 Agent',
        icon: '🤖',
        description: '',
        status: 'published',
        agent_metadata: {
          primary_pool: 'general',
          risk_level: 'safe',
          routing_priority: 50,
          cost_level: 'medium',
          model_tier: 'standard',
          model_id: '',
        },
      },
    ],
    paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 100 },
  })
  mocks.updateAgentPoolConfig.mockResolvedValue({ id: 'cfg-1' } as never)
  mocks.updateAdminAppMetadata.mockResolvedValue({ id: 'app-1' } as never)

  const wrapper = mount(AgentPoolView, {
    global: {
      plugins: [pinia],
      stubs: {
        'a-button': buttonStub,
        'a-select': selectStub,
        'a-input-number': inputNumberStub,
        'a-switch': switchStub,
        'a-modal': modalStub,
        'a-form': { template: '<form><slot /></form>' },
        'a-form-item': { template: '<div><slot /></div>' },
        'a-option': { template: '<option />' },
        'a-pagination': { template: '<div />' },
        'a-spin': { template: '<div><slot /></div>' },
        'a-space': { template: '<div><slot /></div>' },
        'a-tag': { template: '<span><slot /></span>' },
        'a-tooltip': { template: '<span><slot /></span>' },
        'a-empty': { template: '<div class="empty-stub" />' },
        'icon-apps': true,
        'icon-poweroff': true,
        'icon-heart-fill': true,
        'icon-plus': true,
        GovernanceModeBanner: { template: '<div />' },
      },
    },
  })

  await flushPromises()
  return wrapper
}

describe('Admin AgentPoolView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads pool configs on mount', async () => {
    const wrapper = await renderView()

    expect(mocks.listAgentPoolConfigs).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('编程 Agent')
  })

  it('renders KPI stats and a deterministic gradient avatar for each config', async () => {
    const wrapper = await renderView()

    // KPI 统计数字来自 /admin/agent-pool/stats 聚合接口
    const text = wrapper.text()
    expect(text).toContain('1')

    // 契约：每行应用名前渲染一个确定性渐变头像（带 linear-gradient 内联样式）
    const avatars = wrapper.findAll('span[style*="linear-gradient"]')
    expect(avatars.length).toBeGreaterThan(0)
  })

  it('pushes primary_pool / risk_level / routing_priority to app metadata while preserving other fields on submit', async () => {
    const wrapper = await renderView()

    // 打开编辑弹窗
    await wrapper.find('[data-testid="pool-edit-cfg-1"]').trigger('click')
    await flushPromises()

    // 修改三个路由治理字段
    await wrapper.find('[data-testid="pool-edit-primary-pool"]').setValue('coding')
    await wrapper.find('[data-testid="pool-edit-risk-level"]').setValue('high')
    await wrapper.find('[data-testid="pool-edit-routing-priority"]').setValue('80')
    await flushPromises()

    // 提交
    await wrapper.find('.modal-ok').trigger('click')
    await flushPromises()

    // 原 AgentPoolConfig 保存逻辑不变
    expect(mocks.updateAgentPoolConfig).toHaveBeenCalledWith(
      'cfg-1',
      expect.objectContaining({ app_id: 'app-1', enabled: true }),
    )

    // 路由字段通过 PATCH /admin/apps/<id>（updateAdminAppMetadata）持久化到 app 元数据，
    // 且合并时保留 agent_metadata 中其余字段（cost_level 等防止覆盖清空）
    expect(mocks.updateAdminAppMetadata).toHaveBeenCalledWith(
      'app-1',
      expect.objectContaining({
        primary_pool: 'coding',
        risk_level: 'high',
        routing_priority: 80,
        cost_level: 'medium',
        model_tier: 'standard',
      }),
    )
  })
})