import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createAdminMcp, deleteAdminMcp, listAdminMcpProviders } from '@/services/admin-mcp'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
  del: vi.fn(),
}))

describe('admin mcp service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists admin mcp providers with search and pagination params and unwraps page data', async () => {
    const pageData = {
      list: [
        {
          id: 'provider-1',
          provider_key: 'db:provider-1',
          name: 'weather_mcp',
          label: '天气MCP',
          icon: '',
          background: '#0f172a',
          description: '天气服务',
          category: 'productivity',
          transport: 'streamable_http',
          url: 'https://example.com/mcp',
          command: '',
          headers: [],
          tool_names: [],
          args: [],
          env: {},
          timeout_seconds: 30,
          source_type: 'custom',
          source_key: 'weather_mcp',
          source_url: 'https://example.com/mcp',
          creator_name: 'Alice',
          creator_avatar: '',
          is_public: true,
          is_bindable: true,
          bind_reason: '',
          published_at: 1710000000,
          created_at: 1710000000,
          updated_at: 1710003600,
          tool_count: 3,
          tools: [],
          binding: {},
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

    const result = await listAdminMcpProviders({
      search_word: 'weather',
      current_page: 1,
      page_size: 20,
      category: '',
    })

    expect(request.get).toHaveBeenCalledWith('/admin/mcp', {
      params: {
        search_word: 'weather',
        current_page: 1,
        page_size: 20,
        category: '',
      },
    })
    expect(result).toEqual(pageData)
  })

  it('createAdminMcp calls POST /admin/mcp with body and unwraps data', async () => {
    const providerData = { id: 'p1', name: 'mcp1' }
    vi.mocked(request.post).mockResolvedValue({ data: providerData } as never)

    const body = { name: 'mcp1', description: 'd', transport: 'streamable_http', url: 'http://x' } as never
    const result = await createAdminMcp(body)

    expect(request.post).toHaveBeenCalledWith('/admin/mcp', { body })
    expect(result).toEqual(providerData)
  })

  it('deleteAdminMcp calls DELETE /admin/mcp/:id', async () => {
    vi.mocked(request.del).mockResolvedValue({ data: {} } as never)

    await deleteAdminMcp('p1')

    expect(request.del).toHaveBeenCalledWith('/admin/mcp/p1', { body: undefined })
  })
})
