import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import RoutingLogsView from '@/views/admin/RoutingLogsView.vue'

const mocks = vi.hoisted(() => ({
  listAdminRoutingLogs: vi.fn(),
  createAdminRoutingQualityFeedback: vi.fn(),
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
}))

vi.mock('@/services/admin-routing-logs', () => ({
  listAdminRoutingLogs: mocks.listAdminRoutingLogs,
}))

vi.mock('@/services/admin-routing-quality', () => ({
  createAdminRoutingQualityFeedback: mocks.createAdminRoutingQualityFeedback,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    error: mocks.messageError,
    success: mocks.messageSuccess,
  },
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) =>
      ({
        'admin.routingLogs.title': 'Routing logs',
        'admin.routingLogs.description': 'Inspect routing logs',
        'admin.routingLogs.total': 'Total logs',
        'admin.routingLogs.success': 'Success',
        'admin.routingLogs.fallback': 'Fallback',
        'admin.routingLogs.credits': 'Total credits',
        'admin.routingLogs.avgLatency': 'Avg latency',
        'admin.routingLogs.filters': 'Filters',
        'admin.routingLogs.account': 'User',
        'admin.routingLogs.agent': 'Agent',
        'admin.routingLogs.tool': 'Tool',
        'admin.routingLogs.model': 'Model',
        'admin.routingLogs.key': 'Key',
        'admin.routingLogs.status': 'Status',
        'admin.routingLogs.startAt': 'Start time',
        'admin.routingLogs.endAt': 'End time',
        'admin.routingLogs.search': 'Search',
        'admin.routingLogs.userQuery': 'User query',
        'admin.routingLogs.classification': 'Classification',
        'admin.routingLogs.agentPool': 'Agent pool',
        'admin.routingLogs.toolPool': 'Tool pool',
        'admin.routingLogs.latency': 'Latency',
        'admin.routingLogs.fallbackReason': 'Fallback reason',
        'admin.routingLogs.loadFailed': 'Failed to load routing logs',
        'admin.routingLogs.feedback': 'Feedback',
        'admin.routingLogs.feedbackForm': 'Routing quality feedback',
        'admin.routingLogs.rating': 'Rating',
        'admin.routingLogs.accuracy': 'Accuracy',
        'admin.routingLogs.latencyScore': 'Latency score',
        'admin.routingLogs.costScore': 'Cost score',
        'admin.routingLogs.safetyScore': 'Safety score',
        'admin.routingLogs.completenessScore': 'Completeness score',
        'admin.routingLogs.comment': 'Feedback comment',
        'admin.routingLogs.submitFeedback': 'Submit feedback',
        'admin.routingLogs.feedbackSuccess': 'Feedback submitted',
        'admin.routingLogs.feedbackFailed': 'Submit failed',
      })[key] ?? key,
  }),
}))

const inputStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template: '<input :value="modelValue" :placeholder="placeholder" />',
}

const buttonStub = {
  props: ['loading', 'size'],
  emits: ['click'],
  template: '<button type="button" @click="$emit(\'click\')"><slot /></button>',
}

const renderView = async () => {
  mocks.createAdminRoutingQualityFeedback.mockResolvedValue({ id: 'feedback-1' })
  mocks.listAdminRoutingLogs.mockResolvedValue({
    list: [
      {
        id: 'log-1',
        account_id: 'account-1',
        user_query: 'Analyze market',
        task_classification: { complexity: 'complex' },
        routing_decision: {},
        agent_candidates: [],
        selected_agents: [],
        filtered_out_agents: [],
        tool_candidates: [],
        selected_tools: [],
        filtered_out_tools: [],
        billing_events: [],
        model_selection: { model_id: 'deepseek-chat' },
        agent_pool_hits: [{ pool: 'research' }],
        tool_pool_hits: [{ pool: 'web' }],
        key_usage: {},
        cost_summary: { total_credits: 3 },
        latency_ms: 1200,
        fallback_reason: 'fallback:task_failed',
        redaction_enabled: true,
        status: 'success',
        created_at: 1893456000,
      },
    ],
    paginator: { total_record: 1 },
    summary: {
      total_count: 1,
      success_count: 1,
      fallback_count: 1,
      total_credits: 3,
      avg_latency_ms: 1200,
      agent_pool_hit_rate: 1,
      tool_pool_hit_rate: 1,
    },
  })

  const wrapper = mount(RoutingLogsView, {
    global: {
      stubs: {
        'a-input': inputStub,
        'a-button': buttonStub,
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('RoutingLogsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads and renders routing log summary and table fields', async () => {
    const wrapper = await renderView()

    expect(mocks.listAdminRoutingLogs).toHaveBeenCalledWith({
      current_page: 1,
      page_size: 20,
      account_id: '',
      status: '',
      agent_id: '',
      agent_pool: '',
      tool_name: '',
      tool_pool: '',
      model_id: '',
      key_id: '',
      start_at: '',
      end_at: '',
    })
    expect(wrapper.text()).toContain('Routing logs')
    expect(wrapper.text()).toContain('Analyze market')
    expect(wrapper.text()).toContain('deepseek-chat')
    expect(wrapper.text()).toContain('research')
    expect(wrapper.text()).toContain('web')
    expect(wrapper.text()).toContain('fallback:task_failed')
  })

  it('submits routing quality feedback for a log', async () => {
    const wrapper = await renderView()

    const buttons = wrapper.findAll('button')
    await buttons[1].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Routing quality feedback')

    await wrapper.findAll('button').at(-1)?.trigger('click')
    await flushPromises()

    expect(mocks.createAdminRoutingQualityFeedback).toHaveBeenCalledWith({
      routing_log_id: 'log-1',
      rating: 5,
      dimension_scores: {
        accuracy: 5,
        latency: 5,
        cost: 5,
        safety: 5,
        completeness: 5,
      },
      comment: '',
    })
    expect(mocks.messageSuccess).toHaveBeenCalledWith('Feedback submitted')
  })
})
