import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { Button } from '@arco-design/web-vue'
import AppConfirmModal from '../AppConfirmModal.vue'
import AppButton from '../AppButton.vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

const readSource = () =>
  readFileSync(resolve(process.cwd(), 'src/components/AppConfirmModal.vue'), 'utf8')

const mountModal = (options: { props?: Record<string, unknown> } = {}) =>
  mount(AppConfirmModal, {
    global: {
      components: { 'a-button': Button },
      stubs: {
        'a-modal': {
          props: ['visible', 'title'],
          template: '<div v-if="visible" class="modal-stub"><slot /></div>',
        },
      },
    },
    ...options,
    props: { visible: true, title: '删除确认', ...(options.props || {}) },
  })

describe('AppConfirmModal.vue', () => {
  it('renders title/message/target when visible', () => {
    const wrapper = mountModal({
      props: { message: '删除后将移入回收站', target: '报告.pdf' },
    })

    expect(wrapper.text()).toContain('删除后将移入回收站')
    expect(wrapper.text()).toContain('报告.pdf')
  })

  it('uses common i18n keys as default button texts', () => {
    const wrapper = mountModal()
    expect(wrapper.text()).toContain('common.cancel')
    expect(wrapper.text()).toContain('common.actions.confirm')
  })

  it('allows overriding button texts', () => {
    const wrapper = mountModal({ props: { cancelText: '取消', confirmText: '移入回收站' } })
    expect(wrapper.text()).toContain('移入回收站')
  })

  it('emits confirm and closes on cancel', async () => {
    const wrapper = mountModal()
    const buttons = wrapper.findAllComponents(AppButton)
    expect(buttons.length).toBe(2)

    // 第二个按钮为确认
    await buttons[1].trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)

    await buttons[0].trigger('click')
    expect(wrapper.emitted('update:visible')?.[0]).toEqual([false])
  })

  it('defaults confirm button to danger and supports primary', () => {
    const danger = mountModal()
    expect(danger.findAllComponents(AppButton)[1].props('variant')).toBe('danger')

    const primary = mountModal({ props: { confirmVariant: 'primary' } })
    expect(primary.findAllComponents(AppButton)[1].props('variant')).toBe('primary')
  })

  it('passes loading to the confirm button', () => {
    const wrapper = mountModal({ props: { loading: true } })
    expect(wrapper.findAllComponents(AppButton)[1].props('loading')).toBe(true)
  })

  it('keeps all colors on theme tokens without hardcoded hex', () => {
    const source = readSource()
    expect(source).toContain('var(--aicss-')
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})
