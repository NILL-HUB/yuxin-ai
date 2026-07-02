import { beforeEach, describe, expect, it, vi } from 'vitest'
import { listAdminDatasetDocuments } from '@/services/admin-dataset-documents'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
}))

describe('admin dataset documents service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('requests admin dataset documents page data and unwraps the response data', async () => {
    const pageData = {
      list: [],
      paginator: {
        total_record: 0,
        total_page: 0,
        current_page: 1,
        page_size: 20,
      },
    }
    vi.mocked(request.get).mockResolvedValue({ data: pageData } as never)

    const result = await listAdminDatasetDocuments('dataset-1', {
      current_page: 1,
      page_size: 20,
      search_word: '',
    })

    expect(request.get).toHaveBeenCalledWith('/admin/datasets/dataset-1/documents', {
      params: {
        current_page: 1,
        page_size: 20,
        search_word: '',
      },
    })
    expect(result).toEqual(pageData)
  })
})
