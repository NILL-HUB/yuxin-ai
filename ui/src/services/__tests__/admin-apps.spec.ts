import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  listAdminApps,
  offlineAdminApp,
  updateAdminAppBasicInfo,
  updateAdminAppIsPublic,
  updateAdminAppMetadata,
} from '@/services/admin-apps'
import * as requestModule from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
  request: vi.fn(),
}))

describe('admin apps service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists admin apps with search and current_page, unwrapping data', async () => {
    vi.mocked(requestModule.get).mockResolvedValue({
      data: {
        list: [{ id: 'app-1', name: 'Demo' }],
        paginator: { total_record: 1, total_page: 1, current_page: 2, page_size: 20 },
      },
    } as never)

    const result = await listAdminApps({ current_page: 2, page_size: 20, search: 'Demo' })

    expect(requestModule.get).toHaveBeenCalledWith('/admin/apps?current_page=2&page_size=20&search=Demo')
    expect(result).toEqual({
      list: [{ id: 'app-1', name: 'Demo' }],
      paginator: { total_record: 1, total_page: 1, current_page: 2, page_size: 20 },
    })
  })

  it('omits search and status when not provided', async () => {
    vi.mocked(requestModule.get).mockResolvedValue({
      data: { list: [], paginator: { total_record: 0, total_page: 0, current_page: 1, page_size: 20 } },
    } as never)

    await listAdminApps({ current_page: 1, page_size: 20 })

    expect(requestModule.get).toHaveBeenCalledWith('/admin/apps?current_page=1&page_size=20')
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
      model_tier: 'standard',
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
          model_tier: 'standard',
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

  it('updates basic info (name/description/icon) with PATCH', async () => {
    vi.mocked(requestModule.request).mockResolvedValue({ id: 'app-1' } as never)

    await updateAdminAppBasicInfo('app-1', {
      name: '编程 Agent',
      description: '面向编程场景的智能体',
      icon: '🤖',
    })

    expect(requestModule.request).toHaveBeenCalledWith('/admin/apps/app-1', {
      method: 'PATCH',
      body: {
        name: '编程 Agent',
        description: '面向编程场景的智能体',
        icon: '🤖',
      },
    })
  })

  it('updates app is_public (publish/unpublish) with PATCH and unwraps data', async () => {
    vi.mocked(requestModule.request).mockResolvedValue({
      data: { id: 'app-1', name: 'Demo', is_public: true },
    } as never)

    const result = await updateAdminAppIsPublic('app-1', true)

    expect(requestModule.request).toHaveBeenCalledWith('/admin/apps/app-1', {
      method: 'PATCH',
      body: { is_public: true },
    })
    expect(result).toEqual({ id: 'app-1', name: 'Demo', is_public: true })
  })

  it('offlines an app with POST and unwraps data', async () => {
    vi.mocked(requestModule.post).mockResolvedValue({ data: {} } as never)

    const result = await offlineAdminApp('app-1')

    expect(requestModule.post).toHaveBeenCalledWith('/admin/apps/app-1/offline')
    expect(result).toEqual({})
  })
})
