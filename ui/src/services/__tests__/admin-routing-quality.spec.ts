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
    vi.mocked(request.post).mockResolvedValue({
      code: 'success',
      message: 'ok',
      data: { id: 'feedback-1' },
    } as never)

    const result = await createAdminRoutingQualityFeedback({
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
    expect(result).toEqual({ id: 'feedback-1' })
  })

  it('lists feedback', async () => {
    vi.mocked(request.get).mockResolvedValue({
      code: 'success',
      message: 'ok',
      data: [{ id: 'feedback-1' }],
    } as never)

    const result = await listAdminRoutingQualityFeedback({ routing_log_id: 'log-1' })

    expect(request.get).toHaveBeenCalledWith('/admin/routing-quality/feedback', {
      params: { routing_log_id: 'log-1' },
    })
    expect(result).toEqual([{ id: 'feedback-1' }])
  })

  it('gets metrics', async () => {
    vi.mocked(request.get).mockResolvedValue({
      code: 'success',
      message: 'ok',
      data: { total_count: 0 },
    } as never)

    const result = await getAdminRoutingQualityMetrics()

    expect(request.get).toHaveBeenCalledWith('/admin/routing-quality/metrics', {
      params: undefined,
    })
    expect(result).toEqual({ total_count: 0 })
  })

  it('gets metrics with time range params', async () => {
    vi.mocked(request.get).mockResolvedValue({
      code: 'success',
      message: 'ok',
      data: { total_count: 3 },
    } as never)

    const result = await getAdminRoutingQualityMetrics({
      start_at: '1700000000',
      end_at: '1700086400',
    })

    expect(request.get).toHaveBeenCalledWith('/admin/routing-quality/metrics', {
      params: { start_at: '1700000000', end_at: '1700086400' },
    })
    expect(result).toEqual({ total_count: 3 })
  })

  it('lists suggestions', async () => {
    vi.mocked(request.get).mockResolvedValue({
      code: 'success',
      message: 'ok',
      data: [{ id: 'suggestion-1' }],
    } as never)

    const result = await listAdminRoutingQualitySuggestions()

    expect(request.get).toHaveBeenCalledWith('/admin/routing-quality/suggestions')
    expect(result).toEqual([{ id: 'suggestion-1' }])
  })
})
