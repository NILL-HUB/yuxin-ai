import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminSandboxView from '@/views/admin/AdminSandboxView.vue'

const mocks = vi.hoisted(() => ({
  getSandboxOverview: vi.fn(),
  listSandboxConfigs: vi.fn(),
  updateSandboxConfig: vi.fn(),
  activateSandboxBackend: vi.fn(),
  probeSandbox: vi.fn(),
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
}))

vi.mock('@/services/admin-sandbox', () => ({
  getSandboxOverview: mocks.getSandboxOverview,
  listSandboxConfigs: mocks.listSandboxConfigs,
  updateSandboxConfig: mocks.updateSandboxConfig,
  activateSandboxBackend: mocks.activateSandboxBackend,
  probeSandbox: mocks.probeSandbox,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    error: mocks.messageError,
    success: mocks.messageSuccess,
    warning: vi.fn(),
    info: vi.fn(),
  },
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

vi.mock('@/stores/admin', () => ({
  useAdminStore: () => ({ hasPermission: () => true }),
}))

vi.mock('@/utils/error', () => ({
  getErrorMessage: (_error: unknown, fallback: string) => fallback,
}))

const cardStub = { template: '<div class="arco-card"><slot name="title" /><slot /></div>' }
const buttonStub = {
  props: ['loading', 'disabled'],
  emits: ['click'],
  template: '<button type="button" @click="$emit(\'click\')"><slot /></button>',
}
const inputStub = {
  props: ['modelValue', 'placeholder', 'disabled'],
  emits: ['update:modelValue'],
  template: '<input :value="modelValue" />',
}
const tagStub = { template: '<span class="arco-tag"><slot /></span>' }
const radioGroupStub = {
  props: ['modelValue', 'disabled'],
  emits: ['change'],
  template: '<div class="arco-radio-group"><slot /></div>',
}
const radioStub = { props: ['value'], template: '<label class="arco-radio"><slot /></label>' }

const overviewItem = (capability: string, activeBackend: string) => ({
  capability,
  active_backend: activeBackend,
  enabled: activeBackend !== 'disabled',
  reason: '',
  configs: {},
  credentials: {},
  credential_keys: [],
  backends: [
    { backend: 'baidu_cfc', label: 'baidu_cfc', is_active: activeBackend === 'baidu_cfc' },
    { backend: 'disabled', label: 'disabled', is_active: activeBackend === 'disabled' },
  ],
})

const configRow = (capability: string, backend: string) => ({
  capability,
  backend,
  label: backend,
  configs: {},
  is_active: false,
  credentials: {},
  credential_keys: [],
})

/** `<script setup>` 组件的内部绑定（测试直接驱动以模拟用户操作）。 */
type SandboxViewVm = {
  selectedBackend: Record<string, string>
  drafts: Record<string, { key: string; value: string }[]>
  selectBackend: (capability: string, backend: string) => void
}

const renderView = async () => {
  mocks.getSandboxOverview.mockResolvedValue({
    data: {
      items: [overviewItem('code_interpreter', 'baidu_cfc'), overviewItem('skill_exec', 'disabled')],
    },
  })
  mocks.listSandboxConfigs.mockResolvedValue({
    data: {
      items: [
        configRow('code_interpreter', 'baidu_cfc'),
        configRow('code_interpreter', 'disabled'),
        configRow('skill_exec', 'disabled'),
      ],
    },
  })
  mocks.updateSandboxConfig.mockResolvedValue({
    data: { item: configRow('code_interpreter', 'disabled') },
  })
  mocks.activateSandboxBackend.mockResolvedValue({
    data: { item: configRow('skill_exec', 'baidu_cfc') },
  })

  const wrapper = mount(AdminSandboxView, {
    global: {
      stubs: {
        'a-card': cardStub,
        'a-button': buttonStub,
        'a-input': inputStub,
        'a-tag': tagStub,
        'a-radio-group': radioGroupStub,
        'a-radio': radioStub,
      },
    },
  })
  await flushPromises()
  return wrapper
}

const vmOf = (wrapper: Awaited<ReturnType<typeof renderView>>) =>
  wrapper.vm as unknown as SandboxViewVm

const clickButtonByText = async (
  wrapper: Awaited<ReturnType<typeof renderView>>,
  text: string,
  index = 0,
) => {
  const buttons = wrapper.findAll('button').filter((button) => button.text() === text)
  expect(buttons.length).toBeGreaterThan(index)
  await buttons[index].trigger('click')
  await flushPromises()
}

describe('AdminSandboxView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads overview and drafts on mount', async () => {
    const wrapper = await renderView()

    expect(mocks.getSandboxOverview).toHaveBeenCalledTimes(1)
    expect(mocks.listSandboxConfigs).toHaveBeenCalledTimes(1)
    expect(vmOf(wrapper).selectedBackend.code_interpreter).toBe('baidu_cfc')
    expect(Object.keys(vmOf(wrapper).drafts)).toContain('skill_exec::disabled')
  })

  it('saving a non-active backend keeps other drafts, preserves selection and warns about activation', async () => {
    const wrapper = await renderView()
    const vm = vmOf(wrapper)

    // 用户在 skill_exec 卡片上编辑了未保存的草稿
    vm.drafts['skill_exec::disabled'] = [{ key: 'endpoint', value: 'https://sandbox.example.com' }]
    // 用户在 code_interpreter 卡片切换到非激活后端并保存
    vm.selectBackend('code_interpreter', 'disabled')
    await wrapper.vm.$nextTick()

    await clickButtonByText(wrapper, 'admin.sandbox.saveConfig')

    expect(mocks.updateSandboxConfig).toHaveBeenCalledWith(
      'code_interpreter',
      'disabled',
      {},
      {},
    )
    // 保存不应整页刷新（不再重新拉配置列表）
    expect(mocks.listSandboxConfigs).toHaveBeenCalledTimes(1)
    // 其它卡片未保存的草稿必须保留
    expect(vm.drafts['skill_exec::disabled']).toEqual([
      { key: 'endpoint', value: 'https://sandbox.example.com' },
    ])
    // 用户选择不被重置
    expect(vm.selectedBackend.code_interpreter).toBe('disabled')
    // 保存 ≠ 切换：提示尚未激活
    expect(mocks.messageSuccess).toHaveBeenCalledWith('admin.sandbox.saveSuccessNotActivated')
  })

  it('saving the active backend refreshes overview only', async () => {
    const wrapper = await renderView()

    await clickButtonByText(wrapper, 'admin.sandbox.saveConfig')

    expect(mocks.updateSandboxConfig).toHaveBeenCalledWith('code_interpreter', 'baidu_cfc', {}, {})
    expect(mocks.listSandboxConfigs).toHaveBeenCalledTimes(1)
    expect(mocks.getSandboxOverview).toHaveBeenCalledTimes(2)
    expect(mocks.messageSuccess).toHaveBeenCalledWith('admin.sandbox.saveSuccess')
  })

  it('activating refreshes overview without rebuilding drafts or resetting selection', async () => {
    const wrapper = await renderView()
    const vm = vmOf(wrapper)

    vm.drafts['code_interpreter::baidu_cfc'] = [{ key: 'profile', value: 'lite' }]
    vm.selectBackend('skill_exec', 'baidu_cfc')
    await wrapper.vm.$nextTick()

    await clickButtonByText(wrapper, 'admin.sandbox.activate', 1)

    expect(mocks.activateSandboxBackend).toHaveBeenCalledWith('skill_exec', 'baidu_cfc')
    expect(mocks.listSandboxConfigs).toHaveBeenCalledTimes(1)
    expect(mocks.getSandboxOverview).toHaveBeenCalledTimes(2)
    expect(vm.selectedBackend.skill_exec).toBe('baidu_cfc')
    expect(vm.drafts['code_interpreter::baidu_cfc']).toEqual([{ key: 'profile', value: 'lite' }])
    expect(mocks.messageSuccess).toHaveBeenCalledWith('admin.sandbox.activateSuccess')
  })
})
