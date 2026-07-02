import { beforeEach, describe, expect, it, vi } from 'vitest'
import { listAdminSkills } from '@/services/admin-skills'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
}))

describe('admin skills service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists admin skills with search and pagination params and unwraps page data', async () => {
    const pageData = {
      list: [
        {
          id: 'skill-1',
          source_key: 'frontend-skill',
          name: 'frontend-skill',
          label: 'Frontend Skill',
          icon: '',
          description: 'Build strong frontend interfaces',
          readme: '',
          category: 'frontend',
          tags: [],
          capabilities: {},
          executor_type: 'prompt',
          tool_count: 0,
          tools: [],
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

    const result = await listAdminSkills({
      search_word: 'frontend',
      current_page: 1,
      page_size: 20,
      category: '',
    })

    expect(request.get).toHaveBeenCalledWith('/admin/skills', {
      params: {
        search_word: 'frontend',
        current_page: 1,
        page_size: 20,
        category: '',
      },
    })
    expect(result).toEqual(pageData)
  })
})
