import { beforeEach, describe, expect, it, vi } from 'vitest'
import { listAdminRoutingLogs } from '@/services/admin-routing-logs'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
}))

describe('admin routing logs service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists routing logs with phase 7 filters', async () => {
    vi.mocked(request.get).mockResolvedValue({
      code: 'success',
      message: 'ok',
      data: {
        list: [],
        paginator: { total_record: 0 },
        summary: { total_count: 0 },
      },
    } as never)

    const result = await listAdminRoutingLogs({
      current_page: 1,
      page_size: 20,
      account_id: 'account-1',
      status: 'success',
      agent_id: 'agent-1',
      agent_pool: 'research',
      tool_name: 'search',
      tool_pool: 'web',
      model_id: 'deepseek-chat',
      key_id: 'key-1',
      start_at: '2026-01-01T00:00:00',
      end_at: '2026-01-02T00:00:00',
    })

    expect(request.get).toHaveBeenCalledWith('/admin/routing-logs', {
      params: {
        current_page: 1,
        page_size: 20,
        account_id: 'account-1',
        status: 'success',
        agent_id: 'agent-1',
        agent_pool: 'research',
        tool_name: 'search',
        tool_pool: 'web',
        model_id: 'deepseek-chat',
        key_id: 'key-1',
        start_at: '2026-01-01T00:00:00',
        end_at: '2026-01-02T00:00:00',
      },
    })
    expect(result).toEqual({
      list: [],
      paginator: { total_record: 0 },
      summary: { total_count: 0 },
    })
  })
})
