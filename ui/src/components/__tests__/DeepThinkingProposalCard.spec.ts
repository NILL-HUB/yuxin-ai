import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import DeepThinkingProposalCard from '../DeepThinkingProposalCard.vue'
import type { DeepThinkingProposal } from '@/views/shared/chat-stream'

const proposal: DeepThinkingProposal = {
  reason: '需要分析多步骤任务，建议进行深度思考',
  estimated_steps: 5,
}

describe('DeepThinkingProposalCard.vue', () => {
  it('should not render when proposal is null', () => {
    const wrapper = mount(DeepThinkingProposalCard, {
      props: { proposal: null },
    })

    expect(wrapper.find('[data-test="deep-thinking-proposal-card"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('建议进行深度思考')
    expect(wrapper.text()).not.toContain(proposal.reason)
  })

  it('should render reason and estimated_steps when proposal is provided', () => {
    const wrapper = mount(DeepThinkingProposalCard, {
      props: { proposal },
    })

    expect(wrapper.text()).toContain('需要分析多步骤任务，建议进行深度思考')
    expect(wrapper.text()).toContain('5 步')
  })

  it('should emit confirm event when confirm button clicked', async () => {
    const wrapper = mount(DeepThinkingProposalCard, {
      props: { proposal },
    })

    await wrapper.get('[data-test="deep-thinking-confirm"]').trigger('click')

    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('should emit cancel event when cancel button clicked', async () => {
    const wrapper = mount(DeepThinkingProposalCard, {
      props: { proposal },
    })

    await wrapper.get('[data-test="deep-thinking-cancel"]').trigger('click')

    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })
})
