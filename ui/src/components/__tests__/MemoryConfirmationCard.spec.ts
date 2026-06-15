import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MemoryConfirmationCard from '../MemoryConfirmationCard.vue'
import type { MemoryCandidatePrompt } from '@/models/memory'

const candidate: MemoryCandidatePrompt = {
  id: 'candidate-1',
  content: '用户偏好使用中文回答',
  confidence: 3,
  occurrences: 3,
}

describe('MemoryConfirmationCard.vue', () => {
  it('should render memory candidate content', () => {
    const wrapper = mount(MemoryConfirmationCard, {
      props: { candidate },
    })

    expect(wrapper.text()).toContain('用户偏好使用中文回答')
    expect(wrapper.text()).toContain('3 次')
  })

  it('should emit confirm event', async () => {
    const wrapper = mount(MemoryConfirmationCard, {
      props: { candidate },
    })

    await wrapper.get('[data-test="memory-confirm"]').trigger('click')

    expect(wrapper.emitted('confirm')?.[0]).toEqual([candidate.id])
  })

  it('should emit ignore event', async () => {
    const wrapper = mount(MemoryConfirmationCard, {
      props: { candidate },
    })

    await wrapper.get('[data-test="memory-ignore"]').trigger('click')

    expect(wrapper.emitted('ignore')?.[0]).toEqual([candidate.id])
  })

  it('should emit never remind event', async () => {
    const wrapper = mount(MemoryConfirmationCard, {
      props: { candidate },
    })

    await wrapper.get('[data-test="memory-never-remind"]').trigger('click')

    expect(wrapper.emitted('never-remind')?.[0]).toEqual([candidate.id])
  })
})
