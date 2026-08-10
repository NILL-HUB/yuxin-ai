import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createAdminWorkflow,
  deleteAdminWorkflow,
  getAdminWorkflow,
  getAdminWorkflowDraftGraph,
  listAdminWorkflows,
  offlineAdminWorkflow,
  publishAdminWorkflow,
  updateAdminWorkflow,
  updateAdminWorkflowDraftGraph,
} from '@/services/admin-workflows'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}))

describe('admin workflows service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists admin workflows with real backend filters and unwraps page data', async () => {
    const pageData = {
      list: [
        {
          id: 'wf-1',
          name: '客服工单分流',
          tool_call_name: 'ticket_router',
          icon: 'robot',
          description: '分流工单到不同队列',
          status: 'published',
          is_public: true,
          created_at: 1710000000,
          updated_at: 1710003600,
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

    const result = await listAdminWorkflows({
      search: '工单',
      status: 'published',
      current_page: 1,
      page_size: 20,
    })

    expect(request.get).toHaveBeenCalledWith('/admin/workflows', {
      params: {
        search: '工单',
        status: 'published',
        current_page: 1,
        page_size: 20,
      },
    })
    expect(result).toEqual(pageData)
  })

  it('gets a single admin workflow and unwraps detail data', async () => {
    const workflow = {
      id: 'wf-1',
      name: '客服工单分流',
      tool_call_name: 'ticket_router',
      icon: 'robot',
      description: '分流工单到不同队列',
      status: 'draft',
      is_public: false,
      created_at: 1710000000,
      updated_at: 1710003600,
    }
    vi.mocked(request.get).mockResolvedValue({ data: workflow } as never)

    const result = await getAdminWorkflow('wf-1')

    expect(request.get).toHaveBeenCalledWith('/admin/workflows/wf-1')
    expect(result).toEqual(workflow)
  })

  it('updates admin workflow status or visibility via real update endpoint', async () => {
    const workflow = {
      id: 'wf-1',
      name: '客服工单分流',
      tool_call_name: 'ticket_router',
      icon: 'robot',
      description: '分流工单到不同队列',
      status: 'published',
      is_public: false,
      created_at: 1710000000,
      updated_at: 1710007200,
    }
    vi.mocked(request.patch).mockResolvedValue({ data: workflow } as never)

    const result = await updateAdminWorkflow('wf-1', {
      status: 'published',
      is_public: false,
    })

    expect(request.patch).toHaveBeenCalledWith('/admin/workflows/wf-1', {
      body: {
        status: 'published',
        is_public: false,
      },
    })
    expect(result).toEqual(workflow)
  })

  it('calls the offline endpoint and unwraps the empty success payload', async () => {
    vi.mocked(request.post).mockResolvedValue({ data: {} } as never)

    const result = await offlineAdminWorkflow('wf-1')

    expect(request.post).toHaveBeenCalledWith('/admin/workflows/wf-1/offline')
    expect(result).toEqual({})
  })

  it('createAdminWorkflow calls POST /admin/workflows with body', async () => {
    const workflow = { id: 'wf-2', name: 'new' }
    vi.mocked(request.post).mockResolvedValue({ data: workflow } as never)

    const body = { name: 'new', description: 'd' } as never
    const result = await createAdminWorkflow(body)

    expect(request.post).toHaveBeenCalledWith('/admin/workflows', { body })
    expect(result).toEqual(workflow)
  })

  it('deleteAdminWorkflow calls DELETE /admin/workflows/:id', async () => {
    vi.mocked(request.del).mockResolvedValue({ data: {} } as never)

    await deleteAdminWorkflow('wf-1')

    expect(request.del).toHaveBeenCalledWith('/admin/workflows/wf-1', { body: undefined })
  })

  it('getAdminWorkflowDraftGraph calls GET /admin/workflows/:id/draft-graph', async () => {
    const graphData = { nodes: [], edges: [] }
    vi.mocked(request.get).mockResolvedValue({ data: graphData } as never)

    const result = await getAdminWorkflowDraftGraph('wf-1')

    expect(request.get).toHaveBeenCalledWith('/admin/workflows/wf-1/draft-graph')
    expect(result).toEqual(graphData)
  })

  it('updateAdminWorkflowDraftGraph calls POST /admin/workflows/:id/draft-graph with body', async () => {
    const graphData = { nodes: [], edges: [] }
    vi.mocked(request.post).mockResolvedValue({ data: graphData } as never)

    const body = { nodes: [], edges: [] } as never
    const result = await updateAdminWorkflowDraftGraph('wf-1', body)

    expect(request.post).toHaveBeenCalledWith('/admin/workflows/wf-1/draft-graph', { body })
    expect(result).toEqual(graphData)
  })

  it('publishAdminWorkflow calls POST /admin/workflows/:id/publish', async () => {
    const workflow = { id: 'wf-1', status: 'published' }
    vi.mocked(request.post).mockResolvedValue({ data: workflow } as never)

    const result = await publishAdminWorkflow('wf-1')

    expect(request.post).toHaveBeenCalledWith('/admin/workflows/wf-1/publish', { body: undefined })
    expect(result).toEqual(workflow)
  })
})
