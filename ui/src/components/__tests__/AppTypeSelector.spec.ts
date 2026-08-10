import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestI18n } from '@/i18n'
import AppTypeSelector from '@/components/AppTypeSelector.vue'
import { APP_TYPE_OPTIONS } from '@/models/app'

// 渲染组件的辅助函数：可指定语言和 props
const mountSelector = (props: Record<string, unknown> = {}, locale: 'zh-CN' | 'en-US' = 'zh-CN') => {
  return mount(AppTypeSelector, {
    props,
    global: {
      plugins: [createTestI18n(locale)],
      stubs: {
        // 桩所有 Arco 图标组件，避免引入真实组件
        'icon-message': true,
        'icon-robot': true,
        'icon-mind-mapping': true,
        'icon-edit': true,
        'icon-check': true,
      },
    },
  })
}

describe('AppTypeSelector.vue', () => {
  it('renders all 4 type options', () => {
    const wrapper = mountSelector({ modelValue: 'chatbot' })

    // 应渲染 4 张卡片，对应 chatbot/agent/workflow/completion
    const cards = wrapper.findAll('.app-type-card')
    expect(cards).toHaveLength(APP_TYPE_OPTIONS.length)
    expect(cards).toHaveLength(4)
  })

  it('highlights selected option', () => {
    const wrapper = mountSelector({ modelValue: 'agent' })

    const cards = wrapper.findAll('.app-type-card')
    // 仅第 2 张卡片（agent）应带 active 类
    expect(cards[0].classes()).not.toContain('active')
    expect(cards[1].classes()).toContain('active')
    expect(cards[2].classes()).not.toContain('active')
    expect(cards[3].classes()).not.toContain('active')
  })

  it('emits update:modelValue on click', async () => {
    const wrapper = mountSelector({ modelValue: 'chatbot' })

    const cards = wrapper.findAll('.app-type-card')
    await cards[2].trigger('click') // 点击 workflow

    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')![0]).toEqual(['workflow'])
  })

  it('does not emit update when disabled', async () => {
    const wrapper = mountSelector({ modelValue: 'chatbot', disabled: true })

    const cards = wrapper.findAll('.app-type-card')
    // 禁用状态下卡片应带 disabled 类
    expect(cards[0].classes()).toContain('disabled')

    await cards[1].trigger('click') // 尝试点击 agent

    // 不应触发任何 update:modelValue 事件
    expect(wrapper.emitted('update:modelValue')).toBeFalsy()
  })

  it('shows correct labels for zh-CN', () => {
    const wrapper = mountSelector({ modelValue: 'chatbot' }, 'zh-CN')

    const titles = wrapper.findAll('.app-type-card-title').map((el) => el.text())
    expect(titles).toEqual(['对话型', 'Agent 型', '工作流型', '补全型'])

    const descs = wrapper.findAll('.app-type-card-desc').map((el) => el.text())
    expect(descs[0]).toBe('多轮对话，支持上下文记忆')
  })

  it('shows correct labels for en-US', () => {
    const wrapper = mountSelector({ modelValue: 'chatbot' }, 'en-US')

    const titles = wrapper.findAll('.app-type-card-title').map((el) => el.text())
    expect(titles).toEqual(['Chatbot', 'Agent', 'Workflow', 'Completion'])

    const descs = wrapper.findAll('.app-type-card-desc').map((el) => el.text())
    expect(descs[0]).toBe('Multi-turn conversation with context memory')
  })

  it('defaults to chatbot when modelValue is not provided', () => {
    const wrapper = mountSelector()

    const cards = wrapper.findAll('.app-type-card')
    // 第一张卡片（chatbot）默认选中
    expect(cards[0].classes()).toContain('active')
  })
})
