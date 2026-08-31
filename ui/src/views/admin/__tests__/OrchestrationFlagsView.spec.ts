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
        'admin.orchestrationFlags.businessGroup': 'Business flags',
        'admin.orchestrationFlags.challengeNeedsChannel': 'Challenge needs channel',
        'admin.orchestrationFlags.otherGroup': 'Other flags',
        'admin.orchestrationFlags.priorityHint': 'Priority hint',
      })[key] ?? key,
    locale: { value: 'en-US' },
  }),
}))

// Stub Arco table/switch to render slot content for text assertions
const tableStub = {
  props: ['columns', 'data', 'pagination', 'rowKey', 'bordered', 'size'],
  template: `<table><tbody><tr v-for="row in data" :key="row.code" :data-code="row.code"><td>{{ row.code }}</td><td>{{ row.name }}</td><td>{{ row.description }}</td><td>{{ row.risk_level }}</td><td>{{ row.fallback_behavior }}</td><td><slot name="enabled" :record="row" /></td></tr></tbody></table>`,
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

const defaultFlags = [
  {
    code: 'AUTH_EMAIL_ENABLED',
    name: 'Email channel',
    description: 'Email verification channel',
    enabled: false,
    risk_level: 'low',
    fallback_behavior: 'disabled',
  },
  {
    code: 'AUTH_PHONE_ENABLED',
    name: 'Phone channel',
    description: 'Phone verification channel',
    enabled: false,
    risk_level: 'low',
    fallback_behavior: 'disabled',
  },
  {
    code: 'AUTH_LOGIN_CHALLENGE_ENABLED',
    name: 'Login challenge',
    description: 'New IP verification challenge',
    enabled: false,
    risk_level: 'medium',
    fallback_behavior: 'disabled',
  },
  {
    code: 'ENABLE_ORCHESTRATOR',
    name: 'Orchestrator',
    description: 'Enable orchestration router',
    enabled: true,
    risk_level: 'medium',
    fallback_behavior: 'direct_answer',
  },
]

const renderView = async (
  permissions: string[] = ['orchestration_flag:read', 'orchestration_flag:update'],
  flags: typeof defaultFlags = defaultFlags,
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

  mocks.listAdminOrchestrationFlags.mockResolvedValue(flags)
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

    const flagRow = wrapper.find('tr[data-code="ENABLE_ORCHESTRATOR"]')
    await flagRow.find('.arco-switch').trigger('click')
    await wrapper.find('.modal-ok-btn').trigger('click')
    await flushPromises()

    expect(mocks.updateAdminOrchestrationFlag).toHaveBeenCalledWith(
      'ENABLE_ORCHESTRATOR',
      { enabled: false },
    )
  })

  it('disables switch when update permission is missing', async () => {
    const wrapper = await renderView(['orchestration_flag:read'])

    expect(wrapper.find('tr[data-code="ENABLE_ORCHESTRATOR"] .arco-switch').attributes('disabled')).toBeDefined()
  })

  it('renders auth flags in a leading business group', async () => {
    const wrapper = await renderView()

    const groupHeaders = wrapper.findAll('.group-header-title').map((node) => node.text())
    expect(groupHeaders[0]).toBe('Business flags')

    const bodyText = wrapper.find('.flags-collapse').text()
    expect(bodyText).toContain('AUTH_EMAIL_ENABLED')
    expect(bodyText).toContain('AUTH_PHONE_ENABLED')
    expect(bodyText).toContain('AUTH_LOGIN_CHALLENGE_ENABLED')
  })

  it('shows challenge dependency hint when enabling challenge with no channel enabled', async () => {
    const wrapper = await renderView()

    expect(wrapper.find('.confirm-warning').exists()).toBe(false)

    const challengeRow = wrapper.find('tr[data-code="AUTH_LOGIN_CHALLENGE_ENABLED"]')
    await challengeRow.find('.arco-switch').trigger('click')
    await flushPromises()

    expect(wrapper.find('.confirm-modal').text()).toContain('Challenge needs channel')
  })

  it('hides challenge dependency hint when a channel is enabled', async () => {
    const flags = defaultFlags.map((flag) =>
      flag.code === 'AUTH_EMAIL_ENABLED' ? { ...flag, enabled: true } : flag,
    )
    const wrapper = await renderView(
      ['orchestration_flag:read', 'orchestration_flag:update'],
      flags,
    )

    const challengeRow = wrapper.find('tr[data-code="AUTH_LOGIN_CHALLENGE_ENABLED"]')
    await challengeRow.find('.arco-switch').trigger('click')
    await flushPromises()

    expect(wrapper.find('.confirm-modal').text()).not.toContain('Challenge needs channel')
  })
})
