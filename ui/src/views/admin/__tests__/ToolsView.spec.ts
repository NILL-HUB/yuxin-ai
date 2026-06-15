import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ToolsView from '@/views/admin/ToolsView.vue'
import { getToolInventory } from '@/services/tool-inventory'

vi.mock('@/services/tool-inventory', () => ({
  getToolInventory: vi.fn(),
}))

describe('Admin ToolsView', () => {
  it('renders governance fields and filters by risk level', async () => {
    vi.mocked(getToolInventory).mockResolvedValue({
      candidates: [
        {
          id: 'tool-1',
          name: 'Search',
          source_type: 'mcp',
          visibility: 'public',
          enabled: true,
          metadata: {
            tool_pool: 'mcp',
            risk_level: 'medium',
            permission_scope: 'public',
            health_status: 'healthy',
            cost_level: 'low',
          },
        },
      ],
      filtered_out_tools: [],
    } as never)

    const wrapper = mount(ToolsView)
    await vi.dynamicImportSettled()

    expect(wrapper.text()).toContain('Search')
    expect(wrapper.text()).toContain('mcp')
    expect(wrapper.text()).toContain('medium')
    expect(wrapper.text()).toContain('public')
    expect(wrapper.text()).toContain('healthy')
    await wrapper.find('[data-test="risk-filter"]').setValue('high')

    expect(getToolInventory).toHaveBeenLastCalledWith(expect.objectContaining({ tool_pool: '', risk_level: 'high' }))
  })
})
