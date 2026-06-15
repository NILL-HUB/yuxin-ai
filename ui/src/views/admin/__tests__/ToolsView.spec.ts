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
          runtime_name: 'mcp__provider_1__search_docs',
          mounted: true,
          mount_reason: 'dynamic_mcp_tool',
          metadata: {
            tool_pool: 'mcp',
            risk_level: 'medium',
            permission_scope: 'public',
            health_status: 'healthy',
            cost_level: 'low',
          },
        },
      ],
      filtered_out_tools: [
        { id: 'tool-2', name: 'Delete', reason: 'forbidden' },
      ],
    } as never)

    const wrapper = mount(ToolsView)
    await vi.dynamicImportSettled()

    expect(wrapper.text()).toContain('Search')
    expect(wrapper.text()).toContain('mcp')
    expect(wrapper.text()).toContain('medium')
    expect(wrapper.text()).toContain('public')
    expect(wrapper.text()).toContain('healthy')
    expect(wrapper.text()).toContain('mcp__provider_1__search_docs')
    expect(wrapper.text()).toContain('dynamic_mcp_tool')
    expect(wrapper.text()).toContain('Delete: forbidden')
    await wrapper.find('[data-test="risk-filter"]').setValue('high')

    expect(getToolInventory).toHaveBeenLastCalledWith(expect.objectContaining({ tool_pool: '', risk_level: 'high' }))
  })
})
