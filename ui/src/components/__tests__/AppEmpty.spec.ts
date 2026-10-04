import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AppEmpty from '../AppEmpty.vue'

const readSource = () => readFileSync(resolve(process.cwd(), 'src/components/AppEmpty.vue'), 'utf8')

describe('AppEmpty.vue', () => {
  it('renders icon/title/hint/actions regions', () => {
    const wrapper = mount(AppEmpty, {
      props: { title: '当前目录为空', hint: '新建一个文件夹开始整理' },
      slots: {
        icon: '<span class="s-icon" />',
        actions: '<button class="s-action">新建文件夹</button>',
      },
    })

    expect(wrapper.find('.app-empty__icon .s-icon').exists()).toBe(true)
    expect(wrapper.text()).toContain('当前目录为空')
    expect(wrapper.text()).toContain('新建一个文件夹开始整理')
    expect(wrapper.find('.app-empty__actions .s-action').exists()).toBe(true)
  })

  it('omits icon and actions regions when slots are absent', () => {
    const wrapper = mount(AppEmpty, { props: { title: '暂无内容' } })

    expect(wrapper.find('.app-empty__icon').exists()).toBe(false)
    expect(wrapper.find('.app-empty__actions').exists()).toBe(false)
  })

  it('maps variant to size classes', () => {
    const page = mount(AppEmpty, { props: { variant: 'page' } })
    expect(page.classes()).toContain('app-empty--page')

    const inline = mount(AppEmpty, { props: { variant: 'inline' } })
    expect(inline.classes()).toContain('app-empty--inline')
  })

  it('keeps all colors on theme tokens without hardcoded hex', () => {
    const source = readSource()

    expect(source).toContain('var(--aicss-')
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})
