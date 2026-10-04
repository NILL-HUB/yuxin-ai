import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { Tag } from '@arco-design/web-vue'
import AppTag from '../AppTag.vue'

const readSource = () => readFileSync(resolve(process.cwd(), 'src/components/AppTag.vue'), 'utf8')

const mountAppTag = (options: Record<string, unknown> = {}) =>
  mount(AppTag, { global: { components: { 'a-tag': Tag } }, ...options })

describe('AppTag.vue', () => {
  it('renders slot content', () => {
    const wrapper = mountAppTag({ slots: { default: '生成产物' } })
    expect(wrapper.text()).toContain('生成产物')
  })

  it('maps variant to arco color (brand uses theme primary chain)', () => {
    const cases = [
      { variant: 'brand', color: 'arcoblue' },
      { variant: 'neutral', color: 'gray' },
      { variant: 'success', color: 'green' },
      { variant: 'warning', color: 'orange' },
      { variant: 'danger', color: 'red' },
      { variant: 'info', color: 'cyan' },
    ] as const

    for (const item of cases) {
      const wrapper = mountAppTag({ props: { variant: item.variant } })
      expect(wrapper.findComponent(Tag).props('color')).toBe(item.color)
    }
  })

  it('defaults to neutral small variant', () => {
    const wrapper = mountAppTag()
    const tag = wrapper.findComponent(Tag)
    expect(tag.props('color')).toBe('gray')
    expect(tag.props('size')).toBe('small')
  })

  it('keeps pill styling in component without hardcoded hex', () => {
    const source = readSource()
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
    expect(source).toContain('border-radius: 999px')
  })
})
