import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import RoutingQualityView from '@/views/admin/RoutingQualityView.vue'

const globalStubs = {
  stubs: {
    'a-tooltip': { template: '<span><slot /></span>' },
  },
}

const mocks = vi.hoisted(() => ({
  getAdminRoutingQualityMetrics: vi.fn(),
  listAdminRoutingQualitySuggestions: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/admin-routing-quality', () => ({
  getAdminRoutingQualityMetrics: mocks.getAdminRoutingQualityMetrics,
  listAdminRoutingQualitySuggestions: mocks.listAdminRoutingQualitySuggestions,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    error: mocks.messageError,
  },
}))

const tValues: Record<string, string> = {
  'admin.routingQuality.title': 'Routing quality',
  'admin.routingQuality.description': 'Review quality',
  'admin.routingQuality.totalCount': 'Total calls',
  'admin.routingQuality.totalCountHint': 'Calls in range',
  'admin.routingQuality.feedbackCount': 'Feedback count',
  'admin.routingQuality.feedbackCountHint': 'Feedback entries',
  'admin.routingQuality.avgRating': 'Average rating',
  'admin.routingQuality.avgRatingHint': 'Average rating out of 5',
  'admin.routingQuality.fallbackRate': 'Fallback rate',
  'admin.routingQuality.fallbackRateHint': 'Calls that fell back',
  'admin.routingQuality.avgLatency': 'Average latency',
  'admin.routingQuality.avgLatencyHint': 'Latency per call',
  'admin.routingQuality.avgCost': 'Average cost',
  'admin.routingQuality.avgCostHint': 'Credits per call',
  'admin.routingQuality.byTaskType': 'By task type',
  'admin.routingQuality.byAgentPool': 'By agent pool',
  'admin.routingQuality.byToolPool': 'By tool pool',
  'admin.routingQuality.byModel': 'By model',
  'admin.routingQuality.suggestions': 'Suggestions',
  'admin.routingQuality.range7d': 'Last 7 days',
  'admin.routingQuality.range30d': 'Last 30 days',
  'admin.routingQuality.range90d': 'Last 90 days',
  'admin.routingQuality.range180d': 'Last 180 days',
  'admin.routingQuality.rangeAll': 'All time',
  'admin.routingQuality.timeRange': 'Time range',
  'admin.routingQuality.countLabel': 'Calls',
  'admin.routingQuality.avgRatingLabel': 'Avg rating',
  'admin.routingQuality.severityHigh': 'High',
  'admin.routingQuality.severityMedium': 'Medium',
  'admin.routingQuality.severityLow': 'Low',
  'admin.routingQuality.statusOpen': 'Open',
  'admin.routingQuality.statusAccepted': 'Accepted',
  'admin.routingQuality.statusDismissed': 'Dismissed',
  'admin.routingQuality.statusApplied': 'Applied',
  'admin.routingQuality.target': 'Target',
  'admin.routingQuality.suggestionType': 'Suggestion type',
  'admin.routingQuality.openSuggestions': '{count} open suggestions',
  'admin.routingQuality.noSuggestions': 'No suggestions',
  'admin.routingQuality.empty': 'No data',
  'admin.routingQuality.loadFailed': 'Load failed',
  'admin.routingQuality.refresh': 'Refresh',
  'admin.routingQuality.loading': 'Loading…',
  'policyChange.accept': 'Accept',
  'policyChange.dismiss': 'Dismiss',
  'policyChange.preview': 'Preview change',
  'policyChange.apply': 'Apply',
  'policyChange.acceptSuccess': 'Suggestion accepted',
  'policyChange.dismissSuccess': 'Suggestion dismissed',
  'policyChange.applySuccess': 'Policy change applied',
  'policyChange.confirmDismiss': 'Confirm dismiss',
  'policyChange.dismissReason': 'Dismiss reason',
  'policyChange.confirmApply': 'Confirm apply',
  'policyChange.policyType': 'Policy type',
  'policyChange.target': 'Target',
  'policyChange.beforeConfig': 'Before config',
  'policyChange.afterConfig': 'After config',
  'common.confirm': 'Confirm',
  'common.cancel': 'Cancel',
}

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, number>) => {
      const template = tValues[key] ?? key
      if (params) {
        return template.replace(/\{(\w+)\}/g, (_, name: string) => String(params[name]))
      }
      return template
    },
  }),
}))

const metricsFixture = {
  total_count: 100,
  feedback_count: 3,
  avg_rating: 4.2,
  fallback_rate: 0.2,
  avg_latency_ms: 120,
  avg_cost_credits: 3.5,
  quality_by_task_type: {
    qa: { count: 70, avg_rating: 4.5 },
    code: { count: 30, avg_rating: 3.8 },
  },
  quality_by_agent_pool: {
    pool_a: { count: 100, avg_rating: 4.2 },
  },
  quality_by_tool_pool: {},
  quality_by_model: {},
}

const renderView = async () => {
  mocks.getAdminRoutingQualityMetrics.mockResolvedValue(metricsFixture)
  mocks.listAdminRoutingQualitySuggestions.mockResolvedValue([
    {
      id: '11111111-2222-3333-4444-555555555555',
      target_type: 'routing',
      target_id: 'fallback_rate',
      suggestion_type: 'review_fallback_rate',
      severity: 'high',
      reason: 'Fallback rate is high',
      evidence: { fallback_rate: 0.4 },
      status: 'open',
    },
  ])

  const wrapper = mount(RoutingQualityView, { global: globalStubs })
  await flushPromises()
  return wrapper
}

describe('RoutingQualityView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-15T00:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads and renders KPI cards, group bars and suggestions', async () => {
    const wrapper = await renderView()

    expect(mocks.getAdminRoutingQualityMetrics).toHaveBeenCalledTimes(1)
    expect(mocks.getAdminRoutingQualityMetrics).toHaveBeenCalledWith({
      start_at: '1765843200',
      end_at: '1768435200',
    })
    expect(wrapper.text()).toContain('Routing quality')
    expect(wrapper.text()).toContain('Total calls')
    expect(wrapper.text()).toContain('100')
    expect(wrapper.text()).toContain('4.2')
    expect(wrapper.text()).toContain('20.0%')
    expect(wrapper.text()).toContain('120 ms')
    expect(wrapper.text()).toContain('3.50')
    expect(wrapper.text()).toContain('问答')
    expect(wrapper.text()).toContain('编码')
    expect(wrapper.text()).toContain('pool_a')
    expect(wrapper.text()).toContain('Suggestions')
    expect(wrapper.text()).toContain('检查降级率')
    expect(wrapper.text()).toContain('降级率超过阈值')
    // 带 id 的可操作建议应展示采纳/驳回/预览按钮
    expect(wrapper.text()).toContain('Accept')
    expect(wrapper.text()).toContain('Dismiss')
    expect(wrapper.text()).toContain('Preview change')
  })

  it('refetches metrics with range params when the range selector changes', async () => {
    const wrapper = await renderView()

    mocks.getAdminRoutingQualityMetrics.mockClear()

    const buttons = wrapper.findAll('button')
    const rangeButtons = buttons.filter((button) => button.attributes('aria-pressed') !== undefined)
    const sevenDayButton = rangeButtons.find((button) => button.text().includes('Last 7 days'))
    expect(sevenDayButton).toBeDefined()

    await sevenDayButton!.trigger('click')
    await flushPromises()

    expect(mocks.getAdminRoutingQualityMetrics).toHaveBeenCalledWith({
      start_at: '1767830400',
      end_at: '1768435200',
    })

    mocks.getAdminRoutingQualityMetrics.mockClear()

    const allTimeButton = rangeButtons.find((button) => button.text().includes('All time'))
    await allTimeButton!.trigger('click')
    await flushPromises()

    expect(mocks.getAdminRoutingQualityMetrics).toHaveBeenCalledWith(undefined)
  })

  it('keeps task type card visible with an empty state when metrics carry no groups', async () => {
    mocks.getAdminRoutingQualityMetrics.mockResolvedValue({
      ...metricsFixture,
      quality_by_task_type: {},
      quality_by_agent_pool: {},
      quality_by_tool_pool: {},
      quality_by_model: {},
    })
    mocks.listAdminRoutingQualitySuggestions.mockResolvedValue([])

    const wrapper = mount(RoutingQualityView, { global: globalStubs })
    await flushPromises()

    expect(wrapper.text()).toContain('By task type')
    expect(wrapper.text()).toContain('No data')
    expect(wrapper.text()).toContain('No suggestions')
  })

  it('shows error message when loading fails', async () => {
    mocks.getAdminRoutingQualityMetrics.mockRejectedValue(new Error('boom'))

    mount(RoutingQualityView, { global: globalStubs })
    await flushPromises()

    expect(mocks.messageError).toHaveBeenCalled()
  })
})
