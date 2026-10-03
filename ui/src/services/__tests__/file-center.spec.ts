import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  deleteFileCenterEntry,
  listAllFileCenterFiles,
  listFileCenterEntries,
} from '@/services/file-center'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}))

describe('file-center service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('unwraps data field for directory listing', async () => {
    vi.mocked(request.get).mockResolvedValue({
      code: 'success',
      message: '',
      data: { items: [{ id: 'f1', name: '产物' }], parent_id: null },
    } as never)

    const result = await listFileCenterEntries(null)

    expect(request.get).toHaveBeenCalledWith('/space/files', { params: {} })
    expect(result.items).toHaveLength(1)
    // 解包后应为纯数据（不含响应外壳字段）
    expect((result as unknown as { code?: string }).code).toBeUndefined()
  })

  it('passes parent_id when listing inside a folder', async () => {
    vi.mocked(request.get).mockResolvedValue({ data: { items: [], parent_id: 'p1' } } as never)

    await listFileCenterEntries('p1')

    expect(request.get).toHaveBeenCalledWith('/space/files', {
      params: { parent_id: 'p1' },
    })
  })

  it('unwraps data field for the all-files page', async () => {
    vi.mocked(request.get).mockResolvedValue({
      data: { items: [], total: 3, page: 2, page_size: 10, total_pages: 1, total_record: 3 },
    } as never)

    const result = await listAllFileCenterFiles(2, 10)

    expect(request.get).toHaveBeenCalledWith('/space/files/all', {
      params: { page: 2, page_size: 10 },
    })
    expect(result.total).toBe(3)
  })

  it('deletes an entry via DELETE on its id', async () => {
    vi.mocked(request.del).mockResolvedValue({ code: 'success', message: '', data: null } as never)

    await deleteFileCenterEntry('e1')

    expect(request.del).toHaveBeenCalledWith('/space/files/e1')
  })
})
