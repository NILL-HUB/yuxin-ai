import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import RoutingQualityView from '@/views/admin/RoutingQualityView.vue'

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

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) =>
      ({
        'admin.routingQuality.title': 'Routing quality',
        'admin.routingQuality.description': 'Review quality',
        'admin.routingQuality.totalCount': 'Total calls',
        'admin.routingQuality.feedbackCount': 'Feedback count',
        'admin.routingQuality.avgRating': 'Average rating',
        'admin.routingQuality.fallbackRate': 'Fallback rate',
        'admin.routingQuality.avgLatency': 'Average latency',
        'admin.routingQuality.avgCost': 'Average cost',
        'admin.routingQuality.byTaskType': 'By task type',
        'admin.routingQuality.suggestions': 'Suggestions',
        'admin.routingQuality.empty': 'No data',
        'admin.routingQuality.loadFailed': 'Load failed',
      })[key] ?? key,
  }),
}))

const renderView = async () => {
  mocks.getAdminRoutingQualityMetrics.mockResolvedValue({
    total_count: 10,
    feedback_count: 3,
    avg_rating: 4.2,
    fallback_rate: 0.2,
    avg_latency_ms: 120,
    avg_cost_credits: 3.5,
    quality_by_task_type: {
      qa: { count: 7, avg_rating: 4.5 },
    },
    quality_by_agent_pool: {},
    quality_by_tool_pool: {},
    quality_by_model: {},
  })
  mocks.listAdminRoutingQualitySuggestions.mockResolvedValue([
    {
      target_type: 'routing',
      target_id: 'fallback_rate',
      suggestion_type: 'review_fallback_rate',
      severity: 'high',
      reason: 'Fallback rate is high',
      evidence: { fallback_rate: 0.4 },
      status: 'open',
    },
  ])

  const wrapper = mount(RoutingQualityView)
  await flushPromises()
  return wrapper
}

describe('RoutingQualityView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads and renders metrics and suggestions', async () => {
    const wrapper = await renderView()

    expect(wrapper.text()).toContain('Routing quality')
    expect(wrapper.text()).toContain('Total calls')
    expect(wrapper.text()).toContain('10')
    expect(wrapper.text()).toContain('qa')
    expect(wrapper.text()).toContain('review_fallback_rate')
  })
})
