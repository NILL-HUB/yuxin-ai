import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import RoutingLogsView from '@/views/admin/RoutingLogsView.vue'

const mocks = vi.hoisted(() => ({
  listAdminRoutingLogs: vi.fn(),
  getRoutingLogStats: vi.fn(),
  getRoutingLogTrend: vi.fn(),
  getRoutingLogDistribution: vi.fn(),
  createAdminRoutingQualityFeedback: vi.fn(),
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
}))

vi.mock('@/services/admin-routing-logs', () => ({
  listAdminRoutingLogs: mocks.listAdminRoutingLogs,
  getRoutingLogStats: mocks.getRoutingLogStats,
  getRoutingLogTrend: mocks.getRoutingLogTrend,
  getRoutingLogDistribution: mocks.getRoutingLogDistribution,
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

const tValues: Record<string, string> = {
  'admin.routingLogs.title': 'Routing logs',
  'admin.routingLogs.description': 'Inspect routing logs',
  'admin.routingLogs.total': '{count} records',
  'admin.routingLogs.credits': 'Total credits',
  'admin.routingLogs.avgLatency': 'Avg latency',
  'admin.routingLogs.filters': 'Filters',
  'admin.routingLogs.account': 'User',
  'admin.routingLogs.agent': 'Agent',
  'admin.routingLogs.tool': 'Tool',
  'admin.routingLogs.model': 'Model',
  'admin.routingLogs.status': 'Status',
  'admin.routingLogs.search': 'Search',
  'admin.routingLogs.userQuery': 'User query',
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
  'admin.routingLogs.executionMode': 'Execution mode',
  'admin.routingLogs.intent': 'Intent',
  'admin.routingLogs.riskLevel': 'Risk level',
  'admin.routingLogs.costPolicy': 'Cost policy',
  'admin.routingLogs.costAllowed': 'Allowed',
  'admin.routingLogs.costDenied': 'Denied',
  'admin.routingLogs.invokeFrom': 'Source',
  'admin.routingLogs.sourceSchedule': 'Scheduled',
  'admin.routingLogs.sourceAssistantAgent': 'Assistant',
  'admin.routingLogs.sourceWebApp': 'Web app',
  'admin.routingLogs.sourceDebugger': 'Debugger',
  'admin.routingLogs.range7d': 'Last 7 days',
  'admin.routingLogs.range30d': 'Last 30 days',
  'admin.routingLogs.range90d': 'Last 90 days',
  'admin.routingLogs.range180d': 'Last 180 days',
  'admin.routingLogs.rangeAll': 'All time',
  'admin.routingLogs.trendAllLabel': 'All time',
  'admin.routingLogs.timeRange': 'Time range',
  'admin.routingLogs.refresh': 'Refresh',
  'admin.routingLogs.totalRequests': 'Total requests',
  'admin.routingLogs.totalCredits': 'Total credits',
  'admin.routingLogs.totalCreditsHint': 'Credits in range',
  'admin.routingLogs.successRate': 'Success rate',
  'admin.routingLogs.fallbackRate': 'Fallback rate',
  'admin.routingLogs.agentPoolHitRate': 'Agent pool hit rate',
  'admin.routingLogs.successCountHint': '{count} succeeded',
  'admin.routingLogs.successRateHint': 'Successful share',
  'admin.routingLogs.fallbackCountHint': '{count} fell back',
  'admin.routingLogs.avgLatencyHint': 'Avg latency per request',
  'admin.routingLogs.toolPoolHitRateHint': 'Tool pool hit {rate}',
  'admin.routingLogs.statusAll': 'All statuses',
  'admin.routingLogs.statusSuccess': 'Success',
  'admin.routingLogs.statusFallback': 'Fallback',
  'admin.routingLogs.statusFailed': 'Failed',
  'admin.routingLogs.statusError': 'Error',
  'admin.routingLogs.statusPending': 'Pending',
  'admin.routingLogs.invokeAll': 'All sources',
  'admin.routingLogs.modelTier': 'Model tier',
  'admin.routingLogs.trendTitle': '7-day trend',
  'admin.routingLogs.trendTitleTemplate': '{range} trend',
  'admin.routingLogs.trendDescription': 'Trend description',
  'admin.routingLogs.trendRequests': 'Requests',
  'admin.routingLogs.trendFallback': 'Fallbacks',
  'admin.routingLogs.trendPeak': 'Daily peak',
  'admin.routingLogs.noData': 'No data',
  'admin.routingLogs.distributionExecution': 'Execution mode',
  'admin.routingLogs.distributionDescription': 'Routing mix',
  'admin.routingLogs.distributionIntent': 'Intent distribution',
  'admin.routingLogs.distributionCreditsLatency': 'Calls Credits Latency',
  'admin.routingLogs.detailTitle': 'Routing log details',
  'admin.routingLogs.detailDescription': 'Search routing decisions',
  'admin.routingLogs.filterDescription': 'Filter description',
  'admin.routingLogs.createdAt': 'Time',
  'admin.routingLogs.complexity': 'Complexity',
  'admin.routingLogs.operations': 'Actions',
  'admin.routingLogs.detail': 'Details',
  'admin.routingLogs.close': 'Close',
  'admin.routingLogs.routingDecisionJson': 'Full routing decision JSON',
  'admin.routingLogs.accountIdPlaceholder': 'User ID',
  'admin.routingLogs.agentIdPlaceholder': 'Agent ID',
  'admin.routingLogs.toolNamePlaceholder': 'Tool name',
  'admin.routingLogs.modelIdPlaceholder': 'Model ID',
  'admin.routingLogs.reset': 'Reset',
  'admin.routingLogs.loading': 'Loading',
  'admin.routingLogs.overviewLoadFailed': 'Overview load failed',
  'admin.routingLogs.commentPlaceholder': 'Optional',
}

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, string | number>) => {
      const template = tValues[key] ?? key
      if (params) {
        return template.replace(/\{(\w+)\}/g, (_, name: string) => String(params[name]))
      }
      return template
    },
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

const tagStub = {
  props: ['color', 'size'],
  template: '<span class="tag-stub"><slot /></span>',
}

const paginationStub = {
  props: ['total', 'current', 'pageSize', 'showTotal'],
  template: '<div class="pagination-stub"></div>',
}

const drawerStub = {
  props: ['visible', 'width'],
  template:
    '<div v-if="visible" class="a-drawer"><div class="a-drawer-title"><slot name="title" /></div><slot /></div>',
}

const modalStub = {
  props: ['visible', 'title'],
  emits: ['ok', 'cancel'],
  template:
    '<div v-if="visible" class="a-modal"><div class="a-modal-title">{{ title }}</div><slot /><button class="a-modal-ok" @click="$emit(\'ok\')">ok</button></div>',
}

const tooltipStub = {
  props: ['content', 'position'],
  template: '<span class="tooltip-stub"><slot /></span>',
}

const sharedStubs = {
  'a-input': inputStub,
  'a-button': buttonStub,
  'a-tag': tagStub,
  'a-pagination': paginationStub,
  'a-drawer': drawerStub,
  'a-modal': modalStub,
  'a-tooltip': tooltipStub,
}

const statsFixture = {
  total_count: 42,
  success_count: 38,
  fallback_count: 2,
  success_rate: 0.9,
  fallback_rate: 0.05,
  total_credits: 120,
  avg_latency_ms: 850,
  agent_pool_hit_rate: 0.9,
  tool_pool_hit_rate: 0.8,
  by_status: { success: { count: 38, credits: 100 } },
}

const trendFixture = {
  granularity: 'day',
  points: [
    {
      timestamp: 1893456000,
      request_count: 5,
      success_count: 4,
      fallback_count: 1,
      total_credits: 10,
      avg_latency_ms: 500,
    },
    {
      timestamp: 1893542400,
      request_count: 8,
      success_count: 7,
      fallback_count: 1,
      total_credits: 20,
      avg_latency_ms: 600,
    },
  ],
}

const logFixture = {
  id: 'log-1',
  account_id: 'account-1',
  user_query: 'Analyze market',
  task_classification: { complexity: 'complex' },
  routing_decision: {
    execution_mode: 'auto',
    intent: 'analysis',
    risk_level: 'low',
    cost_policy: { allowed: true },
  },
  agent_candidates: [],
  filtered_out_agents: [],
  tool_candidates: [],
  filtered_out_tools: [],
  billing_events: [],
  model_selection: { model_id: 'deepseek-chat' },
  agent_pool_hits: [{ pool: 'research' }],
  tool_pool_hits: [{ pool: 'web' }],
  knowledge_hits: [],
  key_usage: {},
  cost_summary: { total_credits: 3 },
  latency_ms: 1200,
  fallback_reason: 'fallback:task_failed',
  redaction_enabled: true,
  invoke_from: 'assistant_agent',
  status: 'success',
  created_at: 1893456000,
}

const renderView = async () => {
  mocks.createAdminRoutingQualityFeedback.mockResolvedValue({ id: 'feedback-1' })
  mocks.listAdminRoutingLogs.mockResolvedValue({
    list: [{ ...logFixture }],
    paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 },
  })
  mocks.getRoutingLogStats.mockResolvedValue({ ...statsFixture })
  mocks.getRoutingLogTrend.mockResolvedValue({ ...trendFixture })
  mocks.getRoutingLogDistribution.mockImplementation(
    ({ dimension }: { dimension: string }) =>
      Promise.resolve({
        dimension,
        items: [
          {
            name: dimension === 'execution_mode' ? 'auto' : dimension === 'intent' ? 'analysis' : 'fast',
            count: dimension === 'execution_mode' ? 30 : 25,
            credits: 80,
            avg_latency_ms: 600,
            percentage: 0.7,
          },
        ],
        total_count: 30,
      }),
  )

  const wrapper = mount(RoutingLogsView, {
    global: {
      stubs: {
        'a-input': inputStub,
        'a-button': buttonStub,
        'a-tag': tagStub,
        'a-pagination': paginationStub,
        'a-drawer': drawerStub,
        'a-modal': modalStub,
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('RoutingLogsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-15T00:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads and renders overview KPIs, trend and distribution sections', async () => {
    const wrapper = await renderView()

    expect(mocks.getRoutingLogStats).toHaveBeenCalledWith({
      start_at: '1765843200',
      end_at: '1768435200',
    })
    expect(mocks.getRoutingLogTrend).toHaveBeenCalledWith({
      start_at: '1765843200',
      end_at: '1768435200',
      granularity: 'day',
    })
    expect(mocks.getRoutingLogDistribution).toHaveBeenCalledWith({
      start_at: '1765843200',
      end_at: '1768435200',
      dimension: 'execution_mode',
      limit: 8,
    })
    expect(mocks.getRoutingLogDistribution).toHaveBeenCalledWith({
      start_at: '1765843200',
      end_at: '1768435200',
      dimension: 'intent',
      limit: 8,
    })
    expect(wrapper.text()).toContain('Routing logs')
    expect(wrapper.text()).toContain('Total requests')
    expect(wrapper.text()).toContain('Success rate')
    expect(wrapper.text()).toContain('Fallback rate')
    expect(wrapper.text()).toContain('Avg latency')
    expect(wrapper.text()).toContain('850 ms')
    expect(wrapper.text()).toContain('90.0%')
    expect(wrapper.text()).toContain('Last 30 days trend')
    expect(wrapper.text()).toContain('Intent distribution')
  })

  it('loads and renders the routing log table with core columns', async () => {
    const wrapper = await renderView()

    expect(mocks.listAdminRoutingLogs).toHaveBeenCalledWith({
      current_page: 1,
      page_size: 20,
      account_id: '',
      status: '',
      invoke_from: '',
      agent_id: '',
      tool_name: '',
      model_id: '',
      start_at: '',
      end_at: '',
    })
    expect(wrapper.text()).toContain('Analyze market')
    expect(wrapper.text()).toContain('deepseek-chat')
    expect(wrapper.text()).toContain('auto')
  })

  it('relaods overview data when the time range changes', async () => {
    const wrapper = await renderView()

    mocks.getRoutingLogStats.mockClear()
    mocks.getRoutingLogTrend.mockClear()
    mocks.getRoutingLogDistribution.mockClear()

    const buttons = wrapper.findAll('button')
    const rangeButtons = buttons.filter((button) => button.attributes('aria-pressed') !== undefined)
    const sevenDayButton = rangeButtons.find((button) => button.text().includes('Last 7 days'))
    expect(sevenDayButton).toBeDefined()

    await sevenDayButton!.trigger('click')
    await flushPromises()

    expect(mocks.getRoutingLogStats).toHaveBeenCalledWith({
      start_at: '1767830400',
      end_at: '1768435200',
    })
    expect(mocks.getRoutingLogTrend).toHaveBeenCalledWith({
      start_at: '1767830400',
      end_at: '1768435200',
      granularity: 'day',
    })
    expect(mocks.getRoutingLogDistribution).toHaveBeenCalledWith({
      start_at: '1767830400',
      end_at: '1768435200',
      dimension: 'execution_mode',
      limit: 8,
    })
  })

  it('shows routing detail drawer and submits quality feedback', async () => {
    const wrapper = await renderView()

    const detailButtons = wrapper.findAll('button').filter((button) => button.text() === 'Details')
    expect(detailButtons.length).toBe(1)
    await detailButtons[0].trigger('click')
    await flushPromises()

    expect(wrapper.find('.a-drawer').exists()).toBe(true)
    expect(wrapper.text()).toContain('Full routing decision JSON')
    expect(wrapper.text()).toContain('research')

    await wrapper.find('.a-drawer').findAll('button').at(-1)?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Routing quality feedback')
    await wrapper.find('.a-modal-ok').trigger('click')
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

  it('runs list search with selected status and source then resets filters', async () => {
    const wrapper = await renderView()

    const selects = wrapper.findAll('select')
    await selects[0].setValue('fallback')
    await selects[1].setValue('schedule')
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('account-9')
    await inputs[1].setValue('agent-9')

    const searchButton = wrapper.findAll('button').find((button) => button.text() === 'Search')
    await searchButton!.trigger('click')
    await flushPromises()

    expect(mocks.listAdminRoutingLogs).toHaveBeenLastCalledWith({
      current_page: 1,
      page_size: 20,
      account_id: 'account-9',
      status: 'fallback',
      invoke_from: 'schedule',
      agent_id: 'agent-9',
      tool_name: '',
      model_id: '',
      start_at: '',
      end_at: '',
    })

    const resetButton = wrapper.findAll('button').find((button) => button.text() === 'Reset')
    await resetButton!.trigger('click')
    await flushPromises()

    expect(mocks.listAdminRoutingLogs).toHaveBeenLastCalledWith({
      current_page: 1,
      page_size: 20,
      account_id: '',
      status: '',
      invoke_from: '',
      agent_id: '',
      tool_name: '',
      model_id: '',
      start_at: '1765843200',
      end_at: '1768435200',
    })
  })

  it('shows an error message when loading fails', async () => {
    mocks.listAdminRoutingLogs.mockRejectedValue(new Error('boom'))
    mocks.getRoutingLogStats.mockRejectedValue(new Error('boom'))

    mount(RoutingLogsView, {
      global: {
        stubs: sharedStubs,
      },
    })
    await flushPromises()

    expect(mocks.messageError).toHaveBeenCalled()
  })
})
