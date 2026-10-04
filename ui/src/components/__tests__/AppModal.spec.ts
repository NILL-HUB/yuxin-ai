import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { Button } from '@arco-design/web-vue'
import AppModal from '../AppModal.vue'
import AppButton from '../AppButton.vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

const readSource = () => readFileSync(resolve(process.cwd(), 'src/components/AppModal.vue'), 'utf8')

const mountModal = (options: { props?: Record<string, unknown>; slots?: Record<string, string> } = {}) =>
  mount(AppModal, {
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
    props: { visible: true, ...(options.props || {}) },
  })

describe('AppModal.vue', () => {
  it('renders slotted content and footer with default texts', () => {
    const wrapper = mountModal({ slots: { default: '<div class="s-body">内容</div>' } })

    expect(wrapper.find('.s-body').exists()).toBe(true)
    expect(wrapper.text()).toContain('common.cancel')
    expect(wrapper.text()).toContain('common.actions.confirm')
  })

  it('hides footer when hideFooter is set', () => {
    const wrapper = mountModal({ props: { hideFooter: true } })
    expect(wrapper.find('.app-modal__footer').exists()).toBe(false)
  })

  it('emits confirm and closes on cancel', async () => {
    const wrapper = mountModal()
    const buttons = wrapper.findAllComponents(AppButton)
    expect(buttons.length).toBe(2)

    await buttons[1].trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)

    await buttons[0].trigger('click')
    expect(wrapper.emitted('update:visible')?.[0]).toEqual([false])
  })

  it('passes variant and loading to the confirm button', () => {
    const wrapper = mountModal({ props: { confirmVariant: 'danger', loading: true } })
    const confirm = wrapper.findAllComponents(AppButton)[1]
    expect(confirm.props('variant')).toBe('danger')
    expect(confirm.props('loading')).toBe(true)
  })

  it('keeps all colors on theme tokens without hardcoded hex', () => {
    const source = readSource()
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})
