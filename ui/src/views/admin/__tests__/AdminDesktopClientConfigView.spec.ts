import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminDesktopClientConfigView from '@/views/admin/AdminDesktopClientConfigView.vue'

const mocks = vi.hoisted(() => ({
  getDesktopClientConfig: vi.fn(),
  saveDesktopClientConfig: vi.fn(),
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
}))

vi.mock('@/services/admin-desktop-client-config', () => ({
  getDesktopClientConfig: mocks.getDesktopClientConfig,
  saveDesktopClientConfig: mocks.saveDesktopClientConfig,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    error: mocks.messageError,
    success: mocks.messageSuccess,
  },
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) =>
      ({
        'admin.desktopClientConfig.title': 'Desktop client',
        'admin.desktopClientConfig.description': 'Configure address',
        'admin.desktopClientConfig.loadFailed': 'Load failed',
        'admin.desktopClientConfig.saved': 'Saved',
        'admin.desktopClientConfig.saveFailed': 'Save failed',
        'admin.desktopClientConfig.apiOriginLabel': 'API server',
        'admin.desktopClientConfig.apiOriginPlaceholder': 'http://127.0.0.1',
        'admin.desktopClientConfig.emptyHint': 'Leave empty for same origin',
        'admin.desktopClientConfig.save': 'Save',
      })[key] ?? key,
  }),
}))

describe('AdminDesktopClientConfigView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  const inputStub = {
    props: ['modelValue', 'placeholder'],
    emits: ['update:modelValue'],
    template: '<input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  }

  const buttonStub = {
    props: ['loading'],
    emits: ['click'],
    template: '<button type="button" @click="$emit(\'click\')"><slot /></button>',
  }

  const mountView = async () => {
    const wrapper = mount(AdminDesktopClientConfigView, {
      global: {
        stubs: {
          'a-input': inputStub,
          'a-button': buttonStub,
          'a-form': { template: '<form><slot /></form>' },
          'a-form-item': { template: '<div><slot /></div>' },
          'a-spin': { template: '<div><slot /></div>' },
        },
      },
    })
    await flushPromises()
    return wrapper
  }

  it('loads config and shows api_origin input', async () => {
    mocks.getDesktopClientConfig.mockResolvedValue({ api_origin: 'http://127.0.0.1' })
    const wrapper = await mountView()

    expect(mocks.getDesktopClientConfig).toHaveBeenCalledTimes(1)
    const input = wrapper.find('input')
    expect((input.element as HTMLInputElement).value).toBe('http://127.0.0.1')
  })

  it('saves config and shows success message', async () => {
    mocks.getDesktopClientConfig.mockResolvedValue({ api_origin: '' })
    mocks.saveDesktopClientConfig.mockResolvedValue({ api_origin: 'https://openllm.cloud' })
    const wrapper = await mountView()

    await wrapper.find('input').setValue('https://openllm.cloud')
    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(mocks.saveDesktopClientConfig).toHaveBeenCalledWith({ api_origin: 'https://openllm.cloud' })
    expect(mocks.messageSuccess).toHaveBeenCalledWith('Saved')
  })
})
