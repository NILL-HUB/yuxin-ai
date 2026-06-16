import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import OrchestrationFlagsView from '@/views/admin/OrchestrationFlagsView.vue'

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
      })[key] ?? key,
  }),
}))

const renderView = async () => {
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

  const wrapper = mount(OrchestrationFlagsView)
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

    await wrapper.find('button').trigger('click')

    expect(mocks.updateAdminOrchestrationFlag).toHaveBeenCalledWith(
      'ENABLE_ORCHESTRATOR',
      { enabled: false },
    )
  })
})
