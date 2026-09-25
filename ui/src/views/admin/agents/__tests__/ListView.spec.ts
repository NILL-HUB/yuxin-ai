import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAdminStore } from '@/stores/admin'
import ListView from '@/views/admin/agents/ListView.vue'

const mocks = vi.hoisted(() => ({
  listAgents: vi.fn(),
  listAssignablePermissions: vi.fn(),
  listBoards: vi.fn(),
  createAgent: vi.fn(),
  updateAgent: vi.fn(),
  deleteAgent: vi.fn(),
  listSchedules: vi.fn(),
  createSchedule: vi.fn(),
  deleteSchedule: vi.fn(),
  getBudgetUsage: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
  messageWarning: vi.fn(),
}))

vi.mock('@/services/admin-agents', () => ({
  listAgents: mocks.listAgents,
  listAssignablePermissions: mocks.listAssignablePermissions,
  listBoards: mocks.listBoards,
  createAgent: mocks.createAgent,
  updateAgent: mocks.updateAgent,
  deleteAgent: mocks.deleteAgent,
  listSchedules: mocks.listSchedules,
  createSchedule: mocks.createSchedule,
  deleteSchedule: mocks.deleteSchedule,
  getBudgetUsage: mocks.getBudgetUsage,
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
  }
})

const routerPush = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush }),
}))

const buttonStub = {
  props: ['type', 'status', 'loading', 'disabled'],
  emits: ['click'],
  template:
    '<button type="button" :disabled="loading || disabled" @click="$emit(\'click\')"><slot /></button>',
}

const tagStub = {
  props: ['color'],
  template: '<span class="tag-stub"><slot /></span>',
}

const renderView = async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAdminStore(pinia).update({
    id: 'admin-1',
    username: 'admin',
    email: 'admin@example.com',
    name: 'Admin',
    avatar: '',
    status: 'active',
    roles: ['super_admin'],
    permissions: ['agent_pool:read', 'agent_pool:manage'],
  })

  mocks.listAgents.mockResolvedValue([
    {
      id: 'agent-1',
      name: '巡检助手',
      description: '每日巡检',
      prompt_key: null,
      granted_permissions: ['model_pool:read', 'app:read', 'workflow:read'],
      automation_policy: { agent_pool: 'supervised' },
      budget_config: {},
      enabled: true,
      created_at: 1710000000,
      updated_at: 1710000000,
    },
  ])
  // 语义化明细（与 /admin/permissions 同一目录 PERMISSION_CATALOG）
  mocks.listAssignablePermissions.mockResolvedValue([
    { code: 'model_pool:read', name: '查看模型池', resource: 'model_pool', action: 'read' },
    { code: 'app:read', name: '查看应用', resource: 'app', action: 'read' },
    { code: 'workflow:read', name: '查看工作流', resource: 'workflow', action: 'read' },
  ])
  mocks.listBoards.mockResolvedValue({ boards: ['agent_pool'], actions: [] })

  const wrapper = mount(ListView, {
    global: {
      plugins: [pinia],
      stubs: {
        'a-button': buttonStub,
        'a-tag': tagStub,
        'a-space': { template: '<div><slot /></div>' },
        'a-tooltip': { template: '<span><slot /></span>' },
        'a-empty': { template: '<div class="empty-stub" />' },
        'a-modal': { template: '<div v-if="visible"><slot /></div>', props: ['visible'] },
        'a-form': { template: '<form><slot /></form>' },
        'a-form-item': { template: '<div><slot /></div>' },
        'a-input': { template: '<input />' },
        'a-textarea': { template: '<textarea />' },
        'a-select': { template: '<select><slot /></select>' },
        'a-input-number': { template: '<input type="number" />' },
        'a-switch': { template: '<input type="checkbox" />' },
        'a-spin': { template: '<div><slot /></div>' },
        'a-pagination': { template: '<div />' },
        'a-table': { template: '<table><slot /></table>' },
        'a-table-column': { template: '<div><slot /></div>' },
        'IconPlus': true,
        'IconMessage': true,
        'IconRobot': true,
        'IconCheckCircleFill': true,
        'IconPauseCircleFill': true,
        'icon-plus': true,
        'icon-message': true,
        'icon-robot': true,
        'icon-check-circle-fill': true,
        'icon-pause-circle-fill': true,
      },
    },
  })

  await flushPromises()
  return wrapper
}

describe('Admin agents ListView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads agents and assignable permissions on mount', async () => {
    const wrapper = await renderView()

    expect(mocks.listAgents).toHaveBeenCalledTimes(1)
    expect(mocks.listAssignablePermissions).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('巡检助手')
  })

  it('renders permission names from the RBAC catalog instead of raw codes', async () => {
    const wrapper = await renderView()

    const text = wrapper.text()
    // 语义化：显示中文名（与角色权限页同一目录）
    expect(text).toContain('查看模型池')
    expect(text).toContain('查看应用')
    // 不应把裸权限码当作主标签文案
    expect(text).not.toContain('model_pool:read')
    expect(text).not.toContain('app:read')
  })

  it('collapses permissions beyond two into a +N indicator', async () => {
    const wrapper = await renderView()

    // 3 个权限 → 前 2 个展示 + 「+1」
    expect(wrapper.text()).toContain('+1')
  })
})
