import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminCliView from '@/views/admin/AdminCliView.vue'
import type { CliProvider } from '@/services/admin-cli'

const mocks = vi.hoisted(() => ({
  listCliProviders: vi.fn(),
  updateCliProvider: vi.fn(),
  deleteCliProvider: vi.fn(),
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
  modalConfirm: vi.fn(),
}))

vi.mock('@/services/admin-cli', () => ({
  listCliProviders: mocks.listCliProviders,
  updateCliProvider: mocks.updateCliProvider,
  deleteCliProvider: mocks.deleteCliProvider,
  createCliProvider: vi.fn(),
}))

vi.mock('@arco-design/web-vue', async () => {
  const actual = await vi.importActual<typeof import('@arco-design/web-vue')>('@arco-design/web-vue')
  return {
    ...actual,
    Message: { error: mocks.messageError, success: mocks.messageSuccess, warning: vi.fn() },
    Modal: { confirm: mocks.modalConfirm },
  }
})

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: { count?: number; name?: string }) =>
      params?.count !== undefined ? `${key}:${params.count}` : params?.name ? `${key}:${params.name}` : key,
  }),
}))

vi.mock('@/stores/admin', () => ({
  useAdminStore: () => ({ hasPermission: () => true }),
}))

vi.mock('@/views/admin/cli/CreateOrUpdateCliModal.vue', () => ({
  default: {
    name: 'CreateOrUpdateCliModal',
    props: ['visible', 'provider'],
    emits: ['update:visible', 'saved'],
    template: '<div class="cli-modal-stub" />',
  },
}))

const switchStub = {
  props: ['modelValue'],
  emits: ['change'],
  template: '<button class="switch" @click="$emit(\'change\', !modelValue)"></button>',
}

const inputStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template:
    '<input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const provider = (overrides: Partial<CliProvider> = {}): CliProvider => ({
  id: 'p-1',
  name: 'ffmpeg',
  label: '视频处理',
  description: '转码字幕',
  category: 'media',
  command: 'ffmpeg',
  args: ['-version'],
  tool_schema: { probe: { description: '探测' } },
  task_keywords: ['转码'],
  timeout_seconds: 30,
  enabled: true,
  is_public: false,
  tool_count: 1,
  ...overrides,
})

const mountView = () =>
  mount(AdminCliView, {
    global: {
      stubs: {
        'a-input': inputStub,
        'a-switch': switchStub,
        'a-select': {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template:
            '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>',
        },
        'a-option': {
          props: ['value'],
          template: '<option :value="value"><slot /></option>',
        },
      },
    },
  })

describe('AdminCliView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads providers on mount and renders rows', async () => {
    mocks.listCliProviders.mockResolvedValue([provider()])
    const wrapper = mountView()
    await flushPromises()

    expect(mocks.listCliProviders).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('ffmpeg')
    expect(wrapper.text()).toContain('admin.adminCli.columns.tools')
    expect(wrapper.text()).toContain(': 1')
  })

  it('filters rows by search keyword', async () => {
    mocks.listCliProviders.mockResolvedValue([
      provider(),
      provider({ id: 'p-2', name: 'git', command: 'git', label: '版本控制' }),
    ])
    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('[data-test="search"]').setValue('git')
    expect(wrapper.text()).not.toContain('ffmpeg')
    expect(wrapper.text()).toContain('git')
  })

  it('toggles enabled via switch and calls updateCliProvider', async () => {
    mocks.listCliProviders.mockResolvedValue([provider({ enabled: true })])
    mocks.updateCliProvider.mockResolvedValue(undefined)
    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('.switch').trigger('click')
    await flushPromises()

    expect(mocks.updateCliProvider).toHaveBeenCalledWith('p-1', { enabled: false })
  })

  it('filters rows by category select', async () => {
    mocks.listCliProviders.mockResolvedValue([
      provider(),
      provider({ id: 'p-2', name: 'git', command: 'git', label: '版本控制', category: 'dev' }),
    ])
    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('select').setValue('dev')
    expect(wrapper.text()).toContain('git')
    expect(wrapper.text()).not.toContain('ffmpeg')
  })

  it('deletes after Modal.confirm onOk', async () => {
    mocks.listCliProviders.mockResolvedValueOnce([provider()]).mockResolvedValue([])
    mocks.deleteCliProvider.mockResolvedValue(undefined)
    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('.delete-btn').trigger('click')
    expect(mocks.modalConfirm).toHaveBeenCalledTimes(1)
    await mocks.modalConfirm.mock.calls[0][0].onOk()
    await flushPromises()

    expect(mocks.deleteCliProvider).toHaveBeenCalledWith('p-1')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('admin.adminCli.deleted')
  })

  it('shows empty state when no providers', async () => {
    mocks.listCliProviders.mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('admin.adminCli.empty')
  })
})
