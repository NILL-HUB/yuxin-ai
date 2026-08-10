import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createAdminApiTool,
  deleteAdminApiTool,
  getAdminApiTool,
  listAdminApiTools,
  updateAdminApiTool,
} from '@/services/admin-tools'
import * as requestModule from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
  del: vi.fn(),
  request: vi.fn(),
}))

describe('admin api tools service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('listAdminApiTools calls GET /admin/api-tools with pagination params', async () => {
    vi.mocked(requestModule.get).mockResolvedValue({
      data: {
        list: [],
        paginator: { total_record: 0, total_page: 0, current_page: 1, page_size: 20 },
      },
    } as never)

    await listAdminApiTools({ current_page: 1, page_size: 20, search_word: 'weather' })

    expect(requestModule.get).toHaveBeenCalledWith('/admin/api-tools', {
      params: { current_page: 1, page_size: 20, search_word: 'weather' },
    })
  })

  it('createAdminApiTool calls POST /admin/api-tools with body', async () => {
    vi.mocked(requestModule.post).mockResolvedValue({ data: { id: 't1' } } as never)

    const body = { name: 'tool', description: 'd', openapi_schema: '', headers: [] } as never
    await createAdminApiTool(body)

    expect(requestModule.post).toHaveBeenCalledWith('/admin/api-tools', { body })
  })

  it('getAdminApiTool calls GET /admin/api-tools/:id', async () => {
    vi.mocked(requestModule.get).mockResolvedValue({ data: { id: 't1' } } as never)

    await getAdminApiTool('t1')

    expect(requestModule.get).toHaveBeenCalledWith('/admin/api-tools/t1')
  })

  it('updateAdminApiTool calls PATCH /admin/api-tools/:id', async () => {
    vi.mocked(requestModule.request).mockResolvedValue({ data: { id: 't1' } } as never)

    const body = { name: 'tool2' } as never
    await updateAdminApiTool('t1', body)

    expect(requestModule.request).toHaveBeenCalledWith('/admin/api-tools/t1', {
      method: 'PATCH',
      body,
    })
  })

  it('deleteAdminApiTool calls DELETE /admin/api-tools/:id', async () => {
    vi.mocked(requestModule.del).mockResolvedValue({ data: {} } as never)

    await deleteAdminApiTool('t1')

    expect(requestModule.del).toHaveBeenCalledWith('/admin/api-tools/t1', { body: undefined })
  })
})
