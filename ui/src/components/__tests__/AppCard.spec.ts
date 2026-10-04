import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AppCard from '../AppCard.vue'

const readSource = () => readFileSync(resolve(process.cwd(), 'src/components/AppCard.vue'), 'utf8')

describe('AppCard.vue', () => {
  it('renders each slot in its own region', () => {
    const wrapper = mount(AppCard, {
      slots: {
        media: '<div class="s-media" />',
        title: '<span class="s-title">标题</span>',
        meta: '<span class="s-meta">标签</span>',
        actions: '<button class="s-action">x</button>',
        default: '<p class="s-body">正文</p>',
      },
    })

    expect(wrapper.find('.app-card__media .s-media').exists()).toBe(true)
    expect(wrapper.find('.app-card__title .s-title').exists()).toBe(true)
    expect(wrapper.find('.app-card__meta .s-meta').exists()).toBe(true)
    expect(wrapper.find('.app-card__actions .s-action').exists()).toBe(true)
    expect(wrapper.find('.s-body').exists()).toBe(true)
  })

  it('omits regions whose slots are absent', () => {
    const wrapper = mount(AppCard)

    expect(wrapper.find('.app-card__media').exists()).toBe(false)
    expect(wrapper.find('.app-card__title').exists()).toBe(false)
    expect(wrapper.find('.app-card__actions').exists()).toBe(false)
  })

  it('maps variant/selected/interactive to classes', () => {
    const outline = mount(AppCard, { props: { variant: 'outline' } })
    expect(outline.classes()).toContain('app-card--outline')

    const interactive = mount(AppCard, { props: { interactive: true, selected: true } })
    expect(interactive.classes()).toContain('app-card--interactive')
    expect(interactive.classes()).toContain('app-card--selected')
  })

  it('applies hover-visibility by default and always when requested', () => {
    const hover = mount(AppCard, { slots: { actions: '<button>x</button>' } })
    expect(hover.find('.app-card__actions').classes()).toContain('app-card__actions--hover')

    const always = mount(AppCard, {
      props: { actionsVisible: 'always' },
      slots: { actions: '<button>x</button>' },
    })
    expect(always.find('.app-card__actions').classes()).toContain('app-card__actions--always')
  })

  it('keeps all colors on theme tokens without hardcoded hex', () => {
    const source = readSource()

    expect(source).toContain('var(--aicss-')
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})
