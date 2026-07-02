import { beforeEach, describe, expect, it, vi } from 'vitest'
import { listAdminDatasets } from '@/services/admin-datasets'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
}))

describe('admin datasets service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists admin datasets with search and pagination params and unwraps page data', async () => {
    const pageData = {
      list: [
        {
          id: 'dataset-1',
          name: 'CRM知识库',
          icon: 'book',
          description: '客服资料',
          document_count: 8,
          related_app_count: 2,
          character_count: 12000,
          creator_name: 'Alice',
          creator_avatar: 'https://example.com/alice.png',
          upload_at: 1710000000,
          updated_at: 1710003600,
          created_at: 1709990000,
        },
      ],
      paginator: {
        total_record: 1,
        total_page: 1,
        current_page: 1,
        page_size: 20,
      },
    }
    vi.mocked(request.get).mockResolvedValue({ data: pageData } as never)

    const result = await listAdminDatasets({
      search_word: 'CRM',
      current_page: 1,
      page_size: 20,
    })

    expect(request.get).toHaveBeenCalledWith('/admin/datasets', {
      params: {
        search_word: 'CRM',
        current_page: 1,
        page_size: 20,
      },
    })
    expect(result).toEqual(pageData)
  })
})
