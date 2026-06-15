import { beforeEach, describe, expect, it, vi } from 'vitest'
import { listAdminApps, updateAdminAppMetadata } from '@/services/admin-apps'
import * as requestModule from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  request: vi.fn(),
}))

describe('admin apps service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists admin apps', async () => {
    vi.mocked(requestModule.get).mockResolvedValue({ list: [] } as never)

    await listAdminApps({ page: 2, page_size: 20 })

    expect(requestModule.get).toHaveBeenCalledWith('/admin/apps?page=2&page_size=20')
  })

  it('updates agent metadata with PATCH', async () => {
    vi.mocked(requestModule.request).mockResolvedValue({ id: 'app-1' } as never)

    await updateAdminAppMetadata('app-1', {
      primary_pool: 'coding',
      secondary_pools: ['office'],
      capabilities: ['frontend'],
      task_types: ['coding'],
      input_modalities: ['text'],
      output_modalities: ['text'],
      risk_level: 'safe',
      model_tier: 'balanced',
      model_id: 'gpt-4.1',
      key_policy: 'default',
      cost_level: 'medium',
      routing_priority: 100,
      allowed_tool_categories: ['browser'],
      quality_score: 0.8,
      success_rate: 0.9,
      latency_p95: 1000,
      max_context_tokens: 8192,
      enabled: true,
    })

    expect(requestModule.request).toHaveBeenCalledWith('/admin/apps/app-1', {
      method: 'PATCH',
      body: {
        agent_metadata: {
          primary_pool: 'coding',
          secondary_pools: ['office'],
          capabilities: ['frontend'],
          task_types: ['coding'],
          input_modalities: ['text'],
          output_modalities: ['text'],
          risk_level: 'safe',
          model_tier: 'balanced',
          model_id: 'gpt-4.1',
          key_policy: 'default',
          cost_level: 'medium',
          routing_priority: 100,
          allowed_tool_categories: ['browser'],
          quality_score: 0.8,
          success_rate: 0.9,
          latency_p95: 1000,
          max_context_tokens: 8192,
          enabled: true,
        },
      },
    })
  })
})
