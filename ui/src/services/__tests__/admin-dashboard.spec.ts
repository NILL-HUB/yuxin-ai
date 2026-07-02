import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getAdminDashboardSummary } from '@/services/admin-dashboard'
import * as adminWorkflowService from '@/services/admin-workflows'

vi.mock('@/services/admin-workflows', () => ({
  listAdminWorkflows: vi.fn(),
}))

describe('admin dashboard service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('aggregates workflow counts from real admin workflow filters', async () => {
    vi.mocked(adminWorkflowService.listAdminWorkflows)
      .mockResolvedValueOnce({
        list: [],
        paginator: { total_record: 12, total_page: 1, current_page: 1, page_size: 1 },
      })
      .mockResolvedValueOnce({
        list: [],
        paginator: { total_record: 5, total_page: 1, current_page: 1, page_size: 1 },
      })
      .mockResolvedValueOnce({
        list: [],
        paginator: { total_record: 4, total_page: 1, current_page: 1, page_size: 1 },
      })

    const result = await getAdminDashboardSummary()

    expect(adminWorkflowService.listAdminWorkflows).toHaveBeenNthCalledWith(1, {
      search: '',
      status: 'all',
      current_page: 1,
      page_size: 1,
    })
    expect(adminWorkflowService.listAdminWorkflows).toHaveBeenNthCalledWith(2, {
      search: '',
      status: 'published',
      current_page: 1,
      page_size: 1,
    })
    expect(adminWorkflowService.listAdminWorkflows).toHaveBeenNthCalledWith(3, {
      search: '',
      status: 'draft',
      current_page: 1,
      page_size: 1,
    })
    expect(result).toEqual({
      workflow_total: 12,
      workflow_published: 5,
      workflow_draft: 4,
    })
  })
})
