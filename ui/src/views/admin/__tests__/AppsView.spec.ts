import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AppsView from '@/views/admin/AppsView.vue'
import { listAdminApps, updateAdminAppMetadata } from '@/services/admin-apps'

vi.mock('@/services/admin-apps', () => ({
  listAdminApps: vi.fn(),
  updateAdminAppMetadata: vi.fn(),
}))

describe('Admin AppsView', () => {
  it('renders agent metadata and saves updates', async () => {
    vi.mocked(listAdminApps).mockResolvedValue({
      list: [
        {
          id: 'app-1',
          name: '编程 Agent',
          agent_metadata: {
            primary_pool: 'coding',
            secondary_pools: ['office'],
            capabilities: ['frontend'],
            task_types: ['coding'],
            input_modalities: ['text'],
            output_modalities: ['text'],
            risk_level: 'safe',
            model_tier: 'standard',
            model_id: 'gpt-4.1',
            key_policy: 'default',
            cost_level: 'medium',
            routing_priority: 100,
            allowed_tool_categories: ['browser'],
            quality_score: 0.8,
            success_rate: 0.9,
            latency_p95: 1000,
            max_context_tokens: 8192,
            enabled: true,
          },
        },
      ],
    } as never)
    vi.mocked(updateAdminAppMetadata).mockResolvedValue({ id: 'app-1' } as never)

    const wrapper = mount(AppsView)
    await vi.dynamicImportSettled()

    expect(wrapper.text()).toContain('编程 Agent')
    const input = wrapper.find('[data-test="primary-pool"]').element as HTMLInputElement
    expect(input.value).toBe('coding')
    await wrapper.find('[data-test="primary-pool"]').setValue('research')
    await wrapper.find('[data-test="save-metadata"]').trigger('click')

    expect(updateAdminAppMetadata).toHaveBeenCalledWith(
      'app-1',
      expect.objectContaining({ primary_pool: 'research' }),
    )
  })
})
