import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import KeyValueEditor from '@/components/config-editors/KeyValueEditor.vue'
import OrderedArgListEditor from '@/components/config-editors/OrderedArgListEditor.vue'
import TagListEditor from '@/components/config-editors/TagListEditor.vue'

const aInput = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue', 'update:model-value'],
  template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const aButton = {
  props: ['disabled'],
  emits: ['click'],
  template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
}

const aCheckbox = {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: '<input type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" />',
}

const aSelect = {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: '<select :value="modelValue"><slot /></select>',
}

const aInputTag = {
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue'],
  template: '<input :value="(modelValue || []).join(\',\')" :disabled="disabled" />',
}

const aTextarea = {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: '<textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const stub = { template: '<span><slot /></span>' }

const globalStubs = {
  'a-input': aInput,
  'a-button': aButton,
  'a-checkbox': aCheckbox,
  'a-select': aSelect,
  'a-option': stub,
  'a-input-tag': aInputTag,
  'a-textarea': aTextarea,
  'icon-plus': stub,
  'icon-delete': stub,
  'icon-edit': stub,
  'icon-up': stub,
  'icon-down': stub,
  'icon-code': stub,
}

const lastEmitted = (wrapper: { emitted: () => Record<string, unknown[][]> }, event = 'update:modelValue') => {
  const emitted = wrapper.emitted()[event]
  return emitted ? emitted[emitted.length - 1][0] : undefined
}

const buttonByText = (wrapper: ReturnType<typeof mount>, text: string) =>
  wrapper.findAll('button').find((node) => node.text().includes(text))

const testIdButton = (wrapper: ReturnType<typeof mount>, testId: string) =>
  wrapper.findAll(`[data-testid="${testId}"]`)

const confirmButton = (wrapper: ReturnType<typeof mount>) => buttonByText(wrapper, '确认')
const lastDeleteButton = (wrapper: ReturnType<typeof mount>) => {
  const buttons = testIdButton(wrapper, 'kv-delete')
  return buttons[buttons.length - 1]
}

describe('KeyValueEditor', () => {
  it('renders existing rows including their values', () => {
    const wrapper = mount(KeyValueEditor, {
      props: { modelValue: [{ key: 'A', value: '1' }] },
      global: { stubs: globalStubs },
    })
    const text = wrapper.text()
    expect(text).toContain('A')
    expect(text).toContain('1')
  })

  it('hides secret values behind the configured placeholder', () => {
    const wrapper = mount(KeyValueEditor, {
      props: { secret: true, modelValue: [{ key: 'ARK_API_KEY', value: 'masked-value' }] },
      global: { stubs: globalStubs },
    })
    const text = wrapper.text()
    expect(text).toContain('ARK_API_KEY')
    expect(text).not.toContain('masked-value')
    expect(text).toContain('已设置')
  })

  it('adds a new row via the add button and confirm', async () => {
    const wrapper = mount(KeyValueEditor, {
      props: { modelValue: [] },
      global: { stubs: globalStubs },
    })
    await buttonByText(wrapper, '新增一项')!.trigger('click')

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('NEW_KEY')
    await inputs[1].setValue('new-value')
    await confirmButton(wrapper)!.trigger('click')

    expect(lastEmitted(wrapper)).toEqual([{ key: 'NEW_KEY', value: 'new-value' }])
  })

  it('keeps the original secret value when the edit input is left blank', async () => {
    const wrapper = mount(KeyValueEditor, {
      props: { secret: true, modelValue: [{ key: 'ARK_API_KEY', value: 'original-secret' }] },
      global: { stubs: globalStubs },
    })
    await testIdButton(wrapper, 'kv-edit')[0].trigger('click')

    const inputs = wrapper.findAll('input')
    expect((inputs[1].element as HTMLInputElement).value).toBe('')
    await inputs[0].setValue('ARK_API_KEY')
    await confirmButton(wrapper)!.trigger('click')

    expect(lastEmitted(wrapper)).toEqual([{ key: 'ARK_API_KEY', value: 'original-secret' }])
  })

  it('rewrites the value when a new secret is provided', async () => {
    const wrapper = mount(KeyValueEditor, {
      props: { secret: true, modelValue: [{ key: 'ARK_API_KEY', value: 'original-secret' }] },
      global: { stubs: globalStubs },
    })
    await testIdButton(wrapper, 'kv-edit')[0].trigger('click')

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('ARK_API_KEY')
    await inputs[1].setValue('rotated-secret')
    await confirmButton(wrapper)!.trigger('click')

    expect(lastEmitted(wrapper)).toEqual([{ key: 'ARK_API_KEY', value: 'rotated-secret' }])
  })

  it('removes a row via the delete button', async () => {
    const wrapper = mount(KeyValueEditor, {
      props: {
        modelValue: [
          { key: 'A', value: '1' },
          { key: 'B', value: '2' },
        ],
      },
      global: { stubs: globalStubs },
    })
    await lastDeleteButton(wrapper).trigger('click')

    expect(lastEmitted(wrapper)).toEqual([{ key: 'A', value: '1' }])
  })

  it('offers no controls in readonly mode', () => {
    const wrapper = mount(KeyValueEditor, {
      props: { readonly: true, modelValue: [{ key: 'A', value: '1' }] },
      global: { stubs: globalStubs },
    })
    expect(wrapper.findAll('button').length).toBe(0)
  })
})

describe('OrderedArgListEditor', () => {
  it('preserves order and allows editing a single argument', async () => {
    const wrapper = mount(OrderedArgListEditor, {
      props: { modelValue: ['-y', 'pkg', '--flag', 'a,b'] },
      global: { stubs: globalStubs },
    })
    const inputs = wrapper.findAll('input')
    expect(inputs.length).toBe(4)
    expect((inputs[3].element as HTMLInputElement).value).toBe('a,b')

    await inputs[3].setValue('a, b c')
    expect(lastEmitted(wrapper)).toEqual(['-y', 'pkg', '--flag', 'a, b c'])
  })

  it('reorders arguments with the up control', async () => {
    const wrapper = mount(OrderedArgListEditor, {
      props: { modelValue: ['a', 'b'] },
      global: { stubs: globalStubs },
    })
    await testIdButton(wrapper, 'arg-up')[1].trigger('click')
    expect(lastEmitted(wrapper)).toEqual(['b', 'a'])
  })

  it('appends an empty argument', async () => {
    const wrapper = mount(OrderedArgListEditor, {
      props: { modelValue: ['a'] },
      global: { stubs: globalStubs },
    })
    await testIdButton(wrapper, 'arg-add')[0].trigger('click')
    expect(lastEmitted(wrapper)).toEqual(['a', ''])
  })
})

describe('TagListEditor', () => {
  it('passes through existing tags and strips blanks', () => {
    const wrapper = mount(TagListEditor, {
      props: { modelValue: [' a ', '', 'b'] },
      global: { stubs: globalStubs },
    })
    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('a,b')
  })
})
