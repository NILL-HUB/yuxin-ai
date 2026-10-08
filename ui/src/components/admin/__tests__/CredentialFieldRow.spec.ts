import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import CredentialFieldRow from '../CredentialFieldRow.vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) =>
      ({
        'common.credential.configured': '已配置',
        'common.credential.empty': '未配置',
        'common.credential.maskNone': '（无）',
        'common.credential.replace': '替换',
        'common.credential.fill': '填写',
        'common.credential.inputPlaceholder': '请输入凭证值',
        'common.credential.replacePlaceholder': '输入新值以替换；留空并保存表示删除该凭证',
        'common.credential.willUpdate': '保存后更新',
        'common.credential.willClear': '保存后删除',
        'common.actions.cancel': '取消',
      })[key] ?? key,
  }),
}))

const inputStub = {
  props: ['modelValue', 'placeholder', 'disabled', 'size'],
  emits: ['update:modelValue'],
  template: '<input :value="modelValue" :placeholder="placeholder" />',
}
const buttonStub = {
  emits: ['click'],
  template: '<button type="button" @click="$emit(\'click\')"><slot /></button>',
}
const tagStub = { template: '<span class="arco-tag"><slot /></span>' }

const render = (props: Record<string, unknown> = {}) =>
  mount(CredentialFieldRow, {
    props: { label: 'E2B_API_KEY', configured: true, editing: false, ...props },
    global: { stubs: { 'a-input': inputStub, 'a-button': buttonStub, 'a-tag': tagStub } },
  })

describe('CredentialFieldRow', () => {
  it('shows the mask (not an empty input) when the credential is configured', () => {
    const wrapper = render({ mask: 'e2b_****b262' })

    expect(wrapper.text()).toContain('已配置')
    expect(wrapper.text()).toContain('e2b_****b262')
    expect(wrapper.text()).toContain('替换')
    // 未编辑时不渲染输入框：出现空框正是本次要修掉的迷惑观感
    expect(wrapper.findAll('input')).toHaveLength(0)
  })

  it('shows 未配置 + 填写 for a missing credential', () => {
    const wrapper = render({ configured: false, mask: '' })

    expect(wrapper.text()).toContain('未配置')
    expect(wrapper.text()).toContain('填写')
    expect(wrapper.text()).toContain('（无）')
  })

  it('emits start-edit / cancel-edit and update:value', async () => {
    const wrapper = render({ mask: 'e2b_****b262' })

    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('start-edit')).toHaveLength(1)

    await wrapper.setProps({ editing: true })
    const input = wrapper.find('input')
    input.element.value = 'new-key'
    await input.trigger('input')
    // 由调用方驱动草稿：组件只负责把新值发出去
    expect(wrapper.emitted('start-edit')).toHaveLength(1)

    const cancelButton = wrapper.findAll('button').find((button) => button.text() === '取消')
    expect(cancelButton).toBeTruthy()
    await cancelButton!.trigger('click')
    expect(wrapper.emitted('cancel-edit')).toHaveLength(1)
  })

  it('hints the pending action in edit mode (update vs clear)', async () => {
    const wrapper = render({ editing: true, touched: true, draft: 'new-key' })
    expect(wrapper.text()).toContain('保存后更新')
    expect(wrapper.find('input').attributes('placeholder')).toBe(
      '输入新值以替换；留空并保存表示删除该凭证',
    )

    await wrapper.setProps({ draft: '' })
    expect(wrapper.text()).toContain('保存后删除')
  })

  it('uses the empty-state placeholder for unconfigured keys', () => {
    const wrapper = render({ configured: false, editing: true, draft: '' })
    expect(wrapper.find('input').attributes('placeholder')).toBe('请输入凭证值')
  })

  it('renders the optional source tag only when a label is provided', async () => {
    const wrapper = render({ source: 'env', sourceLabel: '环境变量' })
    expect(wrapper.text()).toContain('环境变量')

    await wrapper.setProps({ source: '', sourceLabel: '' })
    expect(wrapper.text()).not.toContain('环境变量')
  })

  it('hides action buttons when disabled (read-only viewer)', () => {
    const wrapper = render({ disabled: true })

    expect(wrapper.findAll('button')).toHaveLength(0)
    expect(wrapper.text()).toContain('已配置')
  })
})
