import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { Button } from '@arco-design/web-vue'
import AppButton from '../AppButton.vue'

const readSource = () => readFileSync(resolve(process.cwd(), 'src/components/AppButton.vue'), 'utf8')

// 注册真实 Arco Button，验证 AppButton → arco 属性/类名映射的真实产物
const mountAppButton = (options: Record<string, unknown> = {}) =>
  mount(AppButton, {
    global: { components: { 'a-button': Button } },
    ...options,
  })

describe('AppButton.vue', () => {
  it('renders default slot content and emits click', async () => {
    const wrapper = mountAppButton({ slots: { default: '新建文件夹' } })

    expect(wrapper.text()).toContain('新建文件夹')

    await wrapper.trigger('click')
    expect(wrapper.emitted('click')).toHaveLength(1)
  })

  it('maps variant to arco button type (primary/secondary/outline/text)', () => {
    const cases = [
      { variant: 'primary', cls: 'arco-btn-primary' },
      { variant: 'secondary', cls: 'arco-btn-secondary' },
      { variant: 'outline', cls: 'arco-btn-outline' },
      { variant: 'text', cls: 'arco-btn-text' },
    ] as const

    for (const item of cases) {
      const wrapper = mountAppButton({ props: { variant: item.variant } })
      expect(wrapper.classes()).toContain(item.cls)
    }
  })

  it('maps danger variant and status prop to arco danger status', () => {
    const danger = mountAppButton({ props: { variant: 'danger' } })
    expect(danger.classes()).toContain('arco-btn-status-danger')
    expect(danger.classes()).toContain('arco-btn-primary')

    const ghostDanger = mountAppButton({
      props: { variant: 'ghost', status: 'danger', iconOnly: true },
    })
    expect(ghostDanger.classes()).toContain('arco-btn-status-danger')
  })

  it('renders circle shape when iconOnly', () => {
    const wrapper = mountAppButton({ props: { iconOnly: true }, slots: { default: 'x' } })
    expect(wrapper.classes()).toContain('arco-btn-shape-circle')
  })

  it('passes loading and disabled to arco button', () => {
    const loading = mountAppButton({ props: { loading: true } })
    expect(loading.classes()).toContain('arco-btn-loading')

    const disabled = mountAppButton({ props: { disabled: true } })
    expect(disabled.classes()).toContain('arco-btn-disabled')
  })

  it('marks htmlType submit for form buttons', () => {
    const wrapper = mountAppButton({ props: { htmlType: 'submit' } })
    expect(wrapper.attributes('type')).toBe('submit')
  })

  it('renders icon slot content', () => {
    const wrapper = mountAppButton({
      slots: { icon: '<span class="stub-icon" />', default: '刷新' },
    })
    expect(wrapper.find('.stub-icon').exists()).toBe(true)
  })

  it('keeps all colors on theme tokens without hardcoded hex', () => {
    const source = readSource()

    expect(source).toContain('var(--aicss-')
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
    expect(source).not.toContain('#165dff')
    expect(source).not.toContain('#1d4ed8')
  })
})
