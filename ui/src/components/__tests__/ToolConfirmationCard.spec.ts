import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ToolConfirmationCard from '../ToolConfirmationCard.vue'
import type { ToolConfirmationPrompt } from '@/models/tool-confirmation'

const prompt: ToolConfirmationPrompt = {
  id: 'confirm-1',
  tool_name: 'delete_user',
  risk_level: 'high',
  spent_credits: 12,
  tool_input: { user_id: 'u1' },
}

describe('ToolConfirmationCard.vue', () => {
  it('should render risk and spent credits', () => {
    const wrapper = mount(ToolConfirmationCard, {
      props: { prompt },
    })

    expect(wrapper.text()).toContain('delete_user')
    expect(wrapper.text()).toContain('high')
    expect(wrapper.text()).toContain('12')
  })

  it('should emit confirm event', async () => {
    const wrapper = mount(ToolConfirmationCard, {
      props: { prompt },
    })

    await wrapper.get('[data-test="tool-confirm"]').trigger('click')

    expect(wrapper.emitted('confirm')?.[0]).toEqual([prompt.id])
  })

  it('should emit cancel event', async () => {
    const wrapper = mount(ToolConfirmationCard, {
      props: { prompt },
    })

    await wrapper.get('[data-test="tool-cancel"]').trigger('click')

    expect(wrapper.emitted('cancel')?.[0]).toEqual([prompt.id])
  })
})
