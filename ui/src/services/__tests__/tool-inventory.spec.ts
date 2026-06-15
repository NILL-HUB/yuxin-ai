import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getToolInventory } from '@/services/tool-inventory'
import * as requestModule from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
}))

describe('tool inventory service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches tool governance inventory with query params', async () => {
    vi.mocked(requestModule.get).mockResolvedValue({ candidates: [] } as never)

    await getToolInventory({
      tool_pool: 'mcp',
      agent_pool: 'office',
      budget_level: 'low',
      allow_confirmation: false,
    })

    expect(requestModule.get).toHaveBeenCalledWith('/tool-inventory', {
      params: {
        tool_pool: 'mcp',
        agent_pool: 'office',
        budget_level: 'low',
        allow_confirmation: 'false',
      },
    })
  })
})
