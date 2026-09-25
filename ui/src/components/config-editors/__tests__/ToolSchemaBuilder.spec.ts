import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ToolSchemaBuilder from '@/components/config-editors/ToolSchemaBuilder.vue'
import McpTemplatePicker from '@/components/config-editors/McpTemplatePicker.vue'
import {
  MCP_CLI_TEMPLATES,
  bumpTemplateToLatest,
  findMcpCliTemplate,
  latestPackageName,
} from '@/components/config-editors/mcp-cli-templates'

const aInput = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue', 'update:model-value'],
  template: '<input :value="modelValue" @input="$emit(\'update:model-value\', $event.target.value)" />',
}

const aTextarea = {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: '<textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const aButton = {
  props: ['disabled'],
  emits: ['click'],
  template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
}

const aCheckbox = {
  props: ['modelValue'],
  emits: ['change', 'update:modelValue'],
  template: `<input
    type="checkbox"
    :checked="modelValue"
    @change="$emit('change', $event.target.checked); $emit('update:modelValue', $event.target.checked)"
  />`,
}

const aSelect = {
  props: ['modelValue'],
  emits: ['change'],
  template: `<select :value="modelValue" @change="$emit('change', $event.target.value)"><slot /></select>`,
}

const aOption = {
  props: ['value'],
  template: '<option :value="value"><slot /></option>',
}

const stub = { template: '<span><slot /></span>' }

const globalStubs = {
  'a-input': aInput,
  'a-textarea': aTextarea,
  'a-button': aButton,
  'a-checkbox': aCheckbox,
  'a-select': aSelect,
  'a-option': aOption,
  'icon-plus': stub,
  'icon-delete': stub,
  'icon-code': stub,
  'icon-refresh': stub,
}

const lastEmitted = (wrapper: { emitted: () => Record<string, unknown[][]> }, event = 'update:modelValue') => {
  const emitted = wrapper.emitted()[event]
  return emitted ? emitted[emitted.length - 1][0] : undefined
}

describe('ToolSchemaBuilder', () => {
  it('renders declared tools and their parameters', () => {
    const wrapper = mount(ToolSchemaBuilder, {
      props: {
        modelValue: {
          echo: {
            description: 'echo text',
            parameters: {
              type: 'object',
              properties: { text: { type: 'string' } },
              required: ['text'],
            },
          },
        },
      },
      global: { stubs: globalStubs },
    })
    const inputs = wrapper.findAll('input')
    const values = inputs.map((node) => (node.element as HTMLInputElement).value)
    expect(values).toContain('echo')
    expect(values).toContain('text')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('echo text')

    const requiredCheckbox = wrapper.find('input[type="checkbox"]')
    expect((requiredCheckbox.element as HTMLInputElement).checked).toBe(true)
  })

  it('adds a tool and emits a JSON-schema shaped object', async () => {
    const wrapper = mount(ToolSchemaBuilder, {
      props: { modelValue: {} },
      global: { stubs: globalStubs },
    })
    const addTool = wrapper.findAll('button').find((node) => node.text().includes('新增工具'))
    await addTool!.trigger('click')

    const nameInput = wrapper.findAll('input')[0]
    await nameInput.setValue('my_tool')
    await nameInput.trigger('input')

    expect(lastEmitted(wrapper)).toEqual({
      my_tool: {
        description: '',
        parameters: { type: 'object', properties: {} },
      },
    })
  })

  it('keeps required list in sync with the required flag', async () => {
    const wrapper = mount(ToolSchemaBuilder, {
      props: {
        modelValue: {
          t1: {
            description: '',
            parameters: { type: 'object', properties: { a: { type: 'string' } }, required: ['a'] },
          },
        },
      },
      global: { stubs: globalStubs },
    })
    const checkbox = wrapper.find('input[type="checkbox"]')
    await checkbox.setValue(false)

    expect(lastEmitted(wrapper)).toEqual({
      t1: { description: '', parameters: { type: 'object', properties: { a: { type: 'string' } } } },
    })
  })
})

describe('mcp-cli-templates', () => {
  it('exposes both Bailian and Ark templates', () => {
    const vendors = MCP_CLI_TEMPLATES.map((template) => template.vendor)
    expect(vendors).toContain('bailian')
    expect(vendors).toContain('ark')
  })

  it('every template declares a tool schema and a cli transport', () => {
    MCP_CLI_TEMPLATES.forEach((template) => {
      expect(template.transport).toBe('cli')
      expect(Object.keys(template.toolSchema).length).toBeGreaterThan(0)
      expect(template.args.length).toBeGreaterThan(0)
    })
  })

  it('secret templates declare their env key name', () => {
    MCP_CLI_TEMPLATES.filter((template) => template.requiresSecret).forEach((template) => {
      expect(template.secretKeyName.length).toBeGreaterThan(0)
    })
  })

  it('finds a template by key', () => {
    expect(findMcpCliTemplate('bailian_model_search')?.vendor).toBe('bailian')
    expect(findMcpCliTemplate('missing')).toBeUndefined()
  })

  it('rewrites the pinned package to @latest for one-click updates', () => {
    const template = MCP_CLI_TEMPLATES[0]
    const bumped = bumpTemplateToLatest(template)
    expect(bumped).toContain(latestPackageName(template.versionedPackage))
    expect(bumped.some((arg) => arg.endsWith('@latest'))).toBe(true)
  })

  it('keeps the package name when building the latest specifier', () => {
    expect(latestPackageName('bailian-cli@2.0.1')).toBe('bailian-cli@latest')
    expect(latestPackageName('@volcengine/ark-cli@1.0.36')).toBe('@volcengine/ark-cli@latest')
  })
})

describe('McpTemplatePicker', () => {
  const selectTemplate = async (wrapper: ReturnType<typeof mount>, key: string) => {
    const select = wrapper.find('select')
    await select.setValue(key)
    await select.trigger('change')
    await wrapper.vm.$nextTick()
  }

  const clickApply = async (wrapper: ReturnType<typeof mount>) => {
    const button = wrapper.findAll('button').find((node) => node.text().includes('填入模板'))
    await button!.trigger('click')
  }

  it('emits the selected template when applying', async () => {
    const wrapper = mount(McpTemplatePicker, { global: { stubs: globalStubs } })
    await selectTemplate(wrapper, 'bailian_model_search')
    await clickApply(wrapper)

    const emitted = wrapper.emitted('apply')
    expect(emitted).toBeTruthy()
    const template = emitted![0][0] as { key: string; vendor: string }
    expect(template.key).toBe('bailian_model_search')
    expect(template.vendor).toBe('bailian')
  })

  it('switches to @latest when the latest toggle is on', async () => {
    const wrapper = mount(McpTemplatePicker, { global: { stubs: globalStubs } })
    await selectTemplate(wrapper, 'bailian_text_chat')

    const checkbox = wrapper.find('input[type="checkbox"]')
    await checkbox.setValue(true)
    await wrapper.vm.$nextTick()

    await clickApply(wrapper)
    const emitted = wrapper.emitted('apply')
    const template = emitted![0][0] as { versionedPackage: string }
    expect(template.versionedPackage.endsWith('@latest')).toBe(true)
  })
})
