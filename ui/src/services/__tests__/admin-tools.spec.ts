import { beforeEach, describe, expect, it, vi } from 'vitest'
import { listAdminTools } from '@/services/admin-tools'
import * as requestModule from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
}))

describe('admin tools service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls GET /admin/tools with pagination and keyword params', async () => {
    vi.mocked(requestModule.get).mockResolvedValue({
      list: [],
      paginator: {
        total_record: 0,
        total_page: 0,
        current_page: 1,
        page_size: 20,
      },
    } as never)

    await listAdminTools({
      current_page: 1,
      page_size: 20,
      keyword: 'weather',
    })

    expect(requestModule.get).toHaveBeenCalledWith('/admin/tools', {
      params: {
        current_page: 1,
        page_size: 20,
        keyword: 'weather',
      },
    })
  })
})
