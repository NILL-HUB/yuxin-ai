import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ToolsView from '@/views/admin/ToolsView.vue'
import { listAdminTools } from '@/services/admin-tools'

vi.mock('@/services/admin-tools', () => ({
  listAdminTools: vi.fn(),
}))

describe('Admin ToolsView', () => {
  it('loads admin tool governance records and supports keyword search', async () => {
    vi.mocked(listAdminTools).mockResolvedValue({
      list: [
        {
          id: 'policy-1',
          tool_id: 'weather-api',
          tool_name: '天气查询',
          source_type: 'api_tool',
          risk_level: 'medium',
          visibility: 'tenant',
          allowed_pools: ['default', 'ops'],
          enabled: true,
          max_invocations_per_request: 3,
          cooldown_seconds: 10,
          require_confirmation: false,
          description: '天气工具',
          updated_at: 1710000000,
        },
      ],
      paginator: {
        total_record: 1,
        total_page: 1,
        current_page: 1,
        page_size: 20,
      },
    } as never)

    const wrapper = mount(ToolsView)
    await flushPromises()

    expect(wrapper.text()).toContain('API工具治理')
    expect(wrapper.text()).toContain('天气查询')
    expect(wrapper.text()).toContain('weather-api')
    expect(wrapper.text()).toContain('medium')
    expect(wrapper.text()).toContain('tenant')
    expect(wrapper.text()).toContain('default, ops')
    expect(wrapper.text()).toContain('3')
    expect(wrapper.text()).toContain('10 秒')
    expect(wrapper.text()).toContain('无需确认')
    expect(wrapper.text()).toContain('天气工具')
    expect(wrapper.text()).not.toContain('挂载原因')
    expect(wrapper.text()).not.toContain('已过滤工具')

    await wrapper.find('[data-test="keyword-filter"]').setValue('city')
    await wrapper.find('[data-test="keyword-filter"]').trigger('keyup.enter')

    expect(listAdminTools).toHaveBeenLastCalledWith({
      current_page: 1,
      page_size: 20,
      keyword: 'city',
    })
  })
})
