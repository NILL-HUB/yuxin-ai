import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminPushConfigView from '@/views/admin/AdminPushConfigView.vue'

const mocks = vi.hoisted(() => ({
  getPushConfig: vi.fn(),
  savePushConfig: vi.fn(),
  testPushSend: vi.fn(),
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
  messageWarning: vi.fn(),
}))

vi.mock('@/services/admin-push-config', () => ({
  getPushConfig: mocks.getPushConfig,
  savePushConfig: mocks.savePushConfig,
  testPushSend: mocks.testPushSend,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    error: mocks.messageError,
    success: mocks.messageSuccess,
    warning: mocks.messageWarning,
  },
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) =>
      ({
        'admin.pushConfig.title': 'System push',
        'admin.pushConfig.description': 'Configure push',
        'admin.pushConfig.qualificationHint': 'Qualification first',
        'admin.pushConfig.enabled': 'Enable',
        'admin.pushConfig.enabledHint': 'hint',
        'admin.pushConfig.primaryProvider': 'Primary',
        'admin.pushConfig.fallbackEnabled': 'Fallback',
        'admin.pushConfig.providerGetui': 'Getui',
        'admin.pushConfig.providerUmeng': 'Umeng',
        'admin.pushConfig.getuiTitle': 'Getui creds',
        'admin.pushConfig.getuiAppId': 'AppID',
        'admin.pushConfig.getuiAppKey': 'AppKey',
        'admin.pushConfig.getuiAppSecret': 'AppSecret',
        'admin.pushConfig.getuiMasterSecret': 'MasterSecret',
        'admin.pushConfig.umengTitle': 'Umeng creds',
        'admin.pushConfig.umengAppKey': 'uAppKey',
        'admin.pushConfig.umengAppMasterSecret': 'uMaster',
        'admin.pushConfig.umengProductionMode': 'Production',
        'admin.pushConfig.umengProductionHint': 'hint',
        'admin.pushConfig.secretPlaceholder': 'keep blank',
        'admin.pushConfig.save': 'Save',
        'admin.pushConfig.saved': 'Saved',
        'admin.pushConfig.saveFailed': 'Save failed',
        'admin.pushConfig.loadFailed': 'Load failed',
        'admin.pushConfig.testTitle': 'Test',
        'admin.pushConfig.testProvider': 'Channel',
        'admin.pushConfig.testDeviceToken': 'Token',
        'admin.pushConfig.testDeviceTokenPlaceholder': 'device token',
        'admin.pushConfig.testSend': 'Send test',
        'admin.pushConfig.testSuccess': 'Sent',
        'admin.pushConfig.testFailure': 'Test failed',
        'admin.pushConfig.testTokenRequired': 'Token required',
      })[key] ?? key,
  }),
}))

const inputStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template: '<input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const inputPasswordStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template: '<input type="password" :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const buttonStub = {
  props: ['loading'],
  emits: ['click'],
  template: '<button type="button" @click="$emit(\'click\')"><slot /></button>',
}

const switchStub = {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: '<span class="arco-switch" />',
}

const checkboxStub = {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: '<span class="arco-checkbox" />',
}

const alertStub = {
  props: ['type'],
  template: '<div class="arco-alert" :class="type"><span class="alert-content"><slot /></span></div>',
}

const renderView = async (configs = {}) => {
  mocks.getPushConfig.mockResolvedValue({
    enabled: true,
    primary_provider: 'getui',
    fallback_enabled: true,
    getui: { app_id: 'app-1', app_key: 'key-1', app_secret: '******', master_secret: '******' },
    umeng: { app_key: 'uk', app_master_secret: '******', production_mode: true },
    ...configs,
  })
  mocks.savePushConfig.mockImplementation(async (payload: Record<string, unknown>) => ({ ...payload }))
  mocks.testPushSend.mockResolvedValue({ ok: true, detail: 'Sent OK' })

  const wrapper = mount(AdminPushConfigView, {
    global: {
      stubs: {
        'a-radio': { props: ['value'], template: '<label><slot /></label>' },
        'a-radio-group': { props: ['modelValue'], template: '<div><slot /></div>' },
        'a-input': inputStub,
        'a-input-password': inputPasswordStub,
        'a-button': buttonStub,
        'a-switch': switchStub,
        'a-checkbox': checkboxStub,
        'a-alert': alertStub,
        'a-divider': { template: '<div class="arco-divider"><slot /></div>' },
        'a-form': { template: '<form><slot /></form>' },
        'a-form-item': { template: '<div><slot /></div>' },
        'a-spin': { template: '<div><slot /></div>' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('AdminPushConfigView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads config and defaults test channel to primary provider', async () => {
    const wrapper = await renderView({ primary_provider: 'umeng' })

    expect(mocks.getPushConfig).toHaveBeenCalledOnce()
    expect(wrapper.vm.form.enabled).toBe(true)
    expect(wrapper.vm.form.primary_provider).toBe('umeng')
    expect(wrapper.vm.testProvider).toBe('umeng')
  })

  it('saves config keeping masked secrets untouched', async () => {
    const wrapper = await renderView()

    const saveButton = wrapper.findAll('button').find((button) => button.text() === 'Save')
    await saveButton!.trigger('click')
    await flushPromises()

    expect(mocks.savePushConfig).toHaveBeenCalledOnce()
    const payload = mocks.savePushConfig.mock.calls[0][0]
    expect(payload.getui.master_secret).toBe('******')
    expect(mocks.messageSuccess).toHaveBeenCalled()
  })

  it('requires a token before test send', async () => {
    const wrapper = await renderView()

    const testButton = wrapper.findAll('button').find((button) => button.text() === 'Send test')
    await testButton!.trigger('click')

    expect(mocks.messageWarning).toHaveBeenCalled()
    expect(mocks.testPushSend).not.toHaveBeenCalled()
  })

  it('sends test push with selected channel and token', async () => {
    const wrapper = await renderView()

    const tokenInput = wrapper.findAll('input').find((input) => input.element.placeholder === 'device token')
    await tokenInput!.setValue('cid-1')
    const testButton = wrapper.findAll('button').find((button) => button.text() === 'Send test')
    await testButton!.trigger('click')
    await flushPromises()

    expect(mocks.testPushSend).toHaveBeenCalledWith('getui', 'cid-1')
    expect(wrapper.find('.arco-alert').text()).toBe('Sent OK')
  })

  it('renders failure detail when test push fails', async () => {
    const wrapper = await renderView()
    mocks.testPushSend.mockResolvedValue({ ok: false, detail: 'invalid token' })

    const tokenInput = wrapper.findAll('input').find((input) => input.element.placeholder === 'device token')
    await tokenInput!.setValue('cid-1')
    const testButton = wrapper.findAll('button').find((button) => button.text() === 'Send test')
    await testButton!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.arco-alert.error').text()).toBe('invalid token')
  })
})
