import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createAdminRoutingQualityFeedback,
  getAdminRoutingQualityMetrics,
  listAdminRoutingQualityFeedback,
  listAdminRoutingQualitySuggestions,
} from '@/services/admin-routing-quality'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
}))

describe('admin routing quality service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('creates feedback', async () => {
    vi.mocked(request.post).mockResolvedValue({ id: 'feedback-1' } as never)

    await createAdminRoutingQualityFeedback({
      routing_log_id: 'log-1',
      rating: 4,
      dimension_scores: { accuracy: 5 },
      comment: 'useful',
    })

    expect(request.post).toHaveBeenCalledWith('/admin/routing-quality/feedback', {
      body: {
        routing_log_id: 'log-1',
        rating: 4,
        dimension_scores: { accuracy: 5 },
        comment: 'useful',
      },
    })
  })

  it('lists feedback', async () => {
    vi.mocked(request.get).mockResolvedValue([] as never)

    await listAdminRoutingQualityFeedback({ routing_log_id: 'log-1' })

    expect(request.get).toHaveBeenCalledWith('/admin/routing-quality/feedback', {
      params: { routing_log_id: 'log-1' },
    })
  })

  it('gets metrics', async () => {
    vi.mocked(request.get).mockResolvedValue({ total_count: 0 } as never)

    await getAdminRoutingQualityMetrics()

    expect(request.get).toHaveBeenCalledWith('/admin/routing-quality/metrics')
  })

  it('lists suggestions', async () => {
    vi.mocked(request.get).mockResolvedValue([] as never)

    await listAdminRoutingQualitySuggestions()

    expect(request.get).toHaveBeenCalledWith('/admin/routing-quality/suggestions')
  })
})
