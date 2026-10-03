import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CreateOrUpdateCliModal from '@/views/admin/cli/CreateOrUpdateCliModal.vue'
import type { CliProvider } from '@/services/admin-cli'

const mocks = vi.hoisted(() => ({
  createCliProvider: vi.fn(),
  updateCliProvider: vi.fn(),
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
}))

vi.mock('@/services/admin-cli', () => ({
  createCliProvider: mocks.createCliProvider,
  updateCliProvider: mocks.updateCliProvider,
}))

vi.mock('@arco-design/web-vue', async () => {
  const actual = await vi.importActual<typeof import('@arco-design/web-vue')>('@arco-design/web-vue')
  return {
    ...actual,
    Message: { error: mocks.messageError, success: mocks.messageSuccess, warning: vi.fn() },
  }
})

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

const inputStub = {
  props: ['modelValue', 'placeholder', 'disabled'],
  emits: ['update:modelValue'],
  template:
    '<input :value="modelValue" :placeholder="placeholder" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}
const textareaStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template:
    '<textarea :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}
const formItemStub = {
  props: ['label'],
  template: '<div class="form-item"><slot /></div>',
}
const modalStub = {
  props: ['visible', 'title', 'width', 'footer'],
  emits: ['cancel'],
  template: '<div class="modal-stub"><div class="modal-title">{{ title }}</div><slot /></div>',
}

const mountModal = (props: { visible: boolean; provider: CliProvider | null }) =>
  mount(CreateOrUpdateCliModal, {
    props,
    global: {
      stubs: {
        'a-modal': modalStub,
        'a-form': { template: '<form><slot /></form>' },
        'a-form-item': formItemStub,
        'a-input': inputStub,
        'a-textarea': textareaStub,
        'a-input-number': inputStub,
        'a-switch': {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template: '<button class="switch" @click="$emit(\'update:modelValue\', !modelValue)"></button>',
        },
      },
    },
  })

const provider: CliProvider = {
  id: 'p-1',
  name: 'ffmpeg',
  label: '视频处理',
  description: '转码与字幕',
  category: 'media',
  command: 'ffmpeg',
  args: ['-version'],
  tool_schema: { probe: { description: '探测媒体信息', parameters: { path: { type: 'string' } } } },
  task_keywords: ['转码'],
  timeout_seconds: 60,
  enabled: true,
  is_public: false,
  tool_count: 1,
}

describe('CreateOrUpdateCliModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('create mode: empty form blocks save with nameRequired', async () => {
    const wrapper = mountModal({ visible: true, provider: null })
    await wrapper.get('.save-btn').trigger('click')

    expect(mocks.createCliProvider).not.toHaveBeenCalled()
    expect(mocks.messageError).toHaveBeenCalledWith('admin.adminCli.modal.nameRequired')
  })

  it('create mode: missing command blocks save with commandRequired', async () => {
    const wrapper = mountModal({ visible: true, provider: null })
    await wrapper.get('[data-test="name"]').setValue('ffmpeg')
    await wrapper.get('.save-btn').trigger('click')

    expect(mocks.createCliProvider).not.toHaveBeenCalled()
    expect(mocks.messageError).toHaveBeenCalledWith('admin.adminCli.modal.commandRequired')
  })

  it('create mode: name+command+tool row submits expanded tool_schema', async () => {
    const wrapper = mountModal({ visible: true, provider: null })
    await wrapper.get('[data-test="name"]').setValue('ffmpeg')
    await wrapper.get('[data-test="command"]').setValue('ffmpeg')
    await wrapper.get('.add-tool').trigger('click')
    await wrapper.get('[data-test="tool-id-0"]').setValue('probe')
    await wrapper.get('[data-test="tool-desc-0"]').setValue('探测媒体信息')
    await wrapper.get('.save-btn').trigger('click')
    await flushPromises()

    expect(mocks.createCliProvider).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'ffmpeg',
        command: 'ffmpeg',
        tool_schema: { probe: { description: '探测媒体信息', parameters: {} } },
      }),
    )
    expect(mocks.messageError).not.toHaveBeenCalled()
  })

  it('create mode: empty capability spec is rejected', async () => {
    const wrapper = mountModal({ visible: true, provider: null })
    await wrapper.get('[data-test="name"]').setValue('ffmpeg')
    await wrapper.get('[data-test="command"]').setValue('ffmpeg')
    await wrapper.get('.save-btn').trigger('click')

    expect(mocks.createCliProvider).not.toHaveBeenCalled()
    expect(mocks.messageError).toHaveBeenCalledWith('admin.adminCli.modal.schemaRequired')
  })

  it('edit mode: prefills provider and submits without name', async () => {
    const wrapper = mountModal({ visible: true, provider })
    await flushPromises()
    expect((wrapper.get('[data-test="command"]').element as HTMLInputElement).value).toBe('ffmpeg')

    mocks.updateCliProvider.mockResolvedValue(undefined)
    await wrapper.get('.save-btn').trigger('click')
    await flushPromises()

    expect(mocks.updateCliProvider).toHaveBeenCalledWith(
      'p-1',
      expect.objectContaining({ command: 'ffmpeg' }),
    )
    const payload = mocks.updateCliProvider.mock.calls[0][1]
    expect('name' in payload).toBe(false)
    expect(payload.tool_schema).toEqual(provider.tool_schema)
  })

  it('env untouched omits env key; clearEnv submits empty env', async () => {
    const wrapper = mountModal({ visible: true, provider })
    mocks.updateCliProvider.mockResolvedValue(undefined)
    await wrapper.get('.save-btn').trigger('click')
    await flushPromises()
    expect('env' in mocks.updateCliProvider.mock.calls[0][1]).toBe(false)

    await wrapper.get('[data-test="clear-env"]').setValue(true)
    await wrapper.get('.save-btn').trigger('click')
    await flushPromises()
    expect(mocks.updateCliProvider.mock.calls[1][1].env).toEqual({})
  })
})
