import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { Button, Tag } from '@arco-design/web-vue'
import MemoryConfirmationCard from '../MemoryConfirmationCard.vue'
import type { MemoryConfirmationItem } from '@/models/memory-confirmation'

const readSource = () =>
  readFileSync(resolve(process.cwd(), 'src/components/MemoryConfirmationCard.vue'), 'utf8')

const items: MemoryConfirmationItem[] = [
  {
    memory_id: 'm1',
    types: ['phone'],
    label: '手机号',
    preview: '我的手机号是 [PHONE_REDACTED]',
  },
]

const mountCard = (props: Record<string, unknown> = {}) =>
  mount(MemoryConfirmationCard, {
    props: { items, ...props },
    global: { components: { 'a-button': Button, 'a-tag': Tag } },
  })

describe('MemoryConfirmationCard.vue', () => {
  it('renders i18n type label and redacted preview', () => {
    const wrapper = mountCard()

    expect(wrapper.text()).toContain('机密记忆读取确认')
    expect(wrapper.text()).toContain('手机号')
    expect(wrapper.text()).toContain('我的手机号是 [PHONE_REDACTED]')
  })

  it('falls back to backend label for unknown types', () => {
    const wrapper = mountCard({
      items: [{ memory_id: 'm2', types: ['unknown_type'], label: '未知类型', preview: 'p' }],
    })

    expect(wrapper.text()).toContain('未知类型')
    expect(wrapper.text()).not.toContain('memoryConfirmation.types')
  })

  it('emits allow / deny from the pending actions', async () => {
    const wrapper = mountCard()

    await wrapper.get('[data-test="memory-allow"]').trigger('click')
    expect(wrapper.emitted('allow')).toHaveLength(1)

    await wrapper.get('[data-test="memory-deny"]').trigger('click')
    expect(wrapper.emitted('deny')).toHaveLength(1)
  })

  it('shows the re-ask hint and hides actions once confirmed', () => {
    const wrapper = mountCard({ status: 'confirmed' })

    expect(wrapper.text()).toContain('已允许读取，正在为你重新提问…')
    expect(wrapper.find('[data-test="memory-allow"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="memory-deny"]').exists()).toBe(false)
  })

  it('keeps colors on theme tokens without hardcoded hex', () => {
    const source = readSource()

    expect(source).toContain('var(--aicss-')
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})
