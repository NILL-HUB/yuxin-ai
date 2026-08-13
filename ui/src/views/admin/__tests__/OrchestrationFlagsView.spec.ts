import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import OrchestrationFlagsView from '@/views/admin/OrchestrationFlagsView.vue'
import { useAdminStore } from '@/stores/admin'

const mocks = vi.hoisted(() => ({
  listAdminOrchestrationFlags: vi.fn(),
  getAdminOrchestrationReleaseCheck: vi.fn(),
  updateAdminOrchestrationFlag: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/admin-orchestration-flags', () => ({
  listAdminOrchestrationFlags: mocks.listAdminOrchestrationFlags,
  getAdminOrchestrationReleaseCheck: mocks.getAdminOrchestrationReleaseCheck,
  updateAdminOrchestrationFlag: mocks.updateAdminOrchestrationFlag,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    error: mocks.messageError,
  },
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) =>
      ({
        'admin.orchestrationFlags.title': 'Orchestration flags',
        'admin.orchestrationFlags.description': 'Manage flags',
        'admin.orchestrationFlags.flagCount': 'Flag count',
        'admin.orchestrationFlags.warningCount': 'Warnings',
        'admin.orchestrationFlags.rollback': 'Rollback action',
        'admin.orchestrationFlags.code': 'Code',
        'admin.orchestrationFlags.name': 'Name',
        'admin.orchestrationFlags.descriptionLabel': 'Description',
        'admin.orchestrationFlags.riskLevel': 'Risk level',
        'admin.orchestrationFlags.fallbackBehavior': 'Fallback behavior',
        'admin.orchestrationFlags.enabled': 'Enabled',
        'admin.orchestrationFlags.on': 'On',
        'admin.orchestrationFlags.off': 'Off',
        'admin.orchestrationFlags.loadFailed': 'Load failed',
        'admin.orchestrationFlags.updateFailed': 'Update failed',
        'admin.orchestrationFlags.poolGovernanceGroup': 'Pool governance',
        'admin.orchestrationFlags.poolGovernanceGroupDesc': 'Pool governance desc',
        'admin.orchestrationFlags.otherGroup': 'Other flags',
        'admin.orchestrationFlags.priorityHint': 'Priority hint',
      })[key] ?? key,
    locale: { value: 'en-US' },
  }),
}))

// Stub Arco table/switch to render slot content for text assertions
const tableStub = {
  props: ['columns', 'data', 'pagination', 'rowKey', 'bordered', 'size'],
  template: `<table><tbody><tr v-for="row in data" :key="row.code"><td>{{ row.code }}</td><td>{{ row.name }}</td><td>{{ row.description }}</td><td>{{ row.risk_level }}</td><td>{{ row.fallback_behavior }}</td><td><slot name="enabled" :record="row" /></td></tr></tbody></table>`,
}

const switchStub = {
  props: ['modelValue', 'loading', 'disabled'],
  emits: ['change', 'update:modelValue'],
  template: '<button type="button" class="arco-switch" :disabled="disabled" @click="$emit(\'change\', !modelValue)"></button>',
}

const modalStub = {
  props: ['visible', 'title', 'okText', 'cancelText', 'okLoading', 'maskClosable', 'width'],
  emits: ['ok', 'cancel', 'update:visible'],
  template: '<div v-if="visible" class="confirm-modal"><slot /><button type="button" class="modal-ok-btn" @click="$emit(\'ok\')">ok</button></div>',
}

const renderView = async (
  permissions: string[] = ['orchestration_flag:read', 'orchestration_flag:update'],
) => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const adminStore = useAdminStore()
  adminStore.update({
    id: 'admin-1',
    username: 'admin',
    email: '',
    name: '',
    avatar: '',
    status: 'active',
    roles: ['admin'],
    permissions,
  })

  mocks.listAdminOrchestrationFlags.mockResolvedValue([
    {
      code: 'ENABLE_ORCHESTRATOR',
      name: 'Orchestrator',
      description: 'Enable orchestration router',
      enabled: true,
      risk_level: 'medium',
      fallback_behavior: 'direct_answer',
    },
  ])
  mocks.getAdminOrchestrationReleaseCheck.mockResolvedValue({
    test_status: {},
    migration_status: {},
    feature_flags: [],
    security_checklist: {},
    cost_metrics: {},
    routing_metrics: {},
    rollback_plan: { primary_action: 'disable_feature_flags' },
    warnings: ['review fallback rate'],
  })
  mocks.updateAdminOrchestrationFlag.mockResolvedValue({ enabled: false })

  const wrapper = mount(OrchestrationFlagsView, {
    global: {
      stubs: {
        'a-table': tableStub,
        'a-switch': switchStub,
        'a-modal': modalStub,
        'a-tag': { template: '<span><slot /></span>' },
        'a-tooltip': { template: '<span><slot /></span>' },
        'a-collapse': { template: '<div><slot /></div>' },
        'a-collapse-item': { template: '<div><slot name="header" /><slot /></div>' },
        'a-spin': { template: '<div><slot /></div>' },
        'a-divider': { template: '<hr />' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('OrchestrationFlagsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads and renders flags and release check summary', async () => {
    const wrapper = await renderView()

    expect(wrapper.text()).toContain('Orchestration flags')
    expect(wrapper.text()).toContain('ENABLE_ORCHESTRATOR')
    expect(wrapper.text()).toContain('direct_answer')
    expect(wrapper.text()).toContain('disable_feature_flags')
  })

  it('updates flag enabled state', async () => {
    const wrapper = await renderView()

    await wrapper.find('.arco-switch').trigger('click')
    await wrapper.find('.modal-ok-btn').trigger('click')
    await flushPromises()

    expect(mocks.updateAdminOrchestrationFlag).toHaveBeenCalledWith(
      'ENABLE_ORCHESTRATOR',
      { enabled: false },
    )
  })

  it('disables switch when update permission is missing', async () => {
    const wrapper = await renderView(['orchestration_flag:read'])

    expect(wrapper.find('.arco-switch').attributes('disabled')).toBeDefined()
  })
})
