import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminSmsConfigView from '@/views/admin/AdminSmsConfigView.vue'

const mocks = vi.hoisted(() => ({
  getSmsConfig: vi.fn(),
  saveSmsConfig: vi.fn(),
  testSmsSend: vi.fn(),
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
  messageWarning: vi.fn(),
}))

vi.mock('@/services/admin-message-config', () => ({
  getMailConfig: vi.fn(),
  saveMailConfig: vi.fn(),
  testMailSend: vi.fn(),
  getSmsConfig: mocks.getSmsConfig,
  saveSmsConfig: mocks.saveSmsConfig,
  testSmsSend: mocks.testSmsSend,
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
        'admin.messageConfig.sms.title': 'SMS config',
        'admin.messageConfig.sms.description': 'Configure SMS',
        'admin.messageConfig.sms.loadFailed': 'Load failed',
        'admin.messageConfig.sms.saved': 'Saved',
        'admin.messageConfig.sms.saveFailed': 'Save failed',
        'admin.messageConfig.sms.provider': 'Provider',
        'admin.messageConfig.sms.providerNone': 'None',
        'admin.messageConfig.sms.providerAliyun': 'Aliyun',
        'admin.messageConfig.sms.providerTencent': 'Tencent',
        'admin.messageConfig.sms.accessKey': 'Access key',
        'admin.messageConfig.sms.accessKeyPlaceholder': 'key id',
        'admin.messageConfig.sms.accessSecret': 'Access secret',
        'admin.messageConfig.sms.accessSecretPlaceholder': 'secret',
        'admin.messageConfig.sms.signName': 'Sign name',
        'admin.messageConfig.sms.signNamePlaceholder': 'sign',
        'admin.messageConfig.sms.region': 'Region',
        'admin.messageConfig.sms.regionPlaceholder': 'ap-guangzhou',
        'admin.messageConfig.sms.sdkAppId': 'SDK App ID',
        'admin.messageConfig.sms.sdkAppIdPlaceholder': 'app id',
        'admin.messageConfig.sms.verifyCodeTemplate': 'Template ID',
        'admin.messageConfig.sms.verifyCodeTemplatePlaceholder': 'SMS_1',
        'admin.messageConfig.sms.providerFieldsRequired': 'Provider fields required',
        'admin.messageConfig.sms.save': 'Save',
        'admin.messageConfig.sms.testSend': 'Test send',
        'admin.messageConfig.sms.testPhonePlaceholder': 'test phone',
        'admin.messageConfig.sms.testPhoneRequired': 'Enter test phone',
        'admin.messageConfig.sms.testSuccess': 'Sent',
        'admin.messageConfig.sms.testFailure': 'Send failed',
        'admin.messageConfig.sms.testFailed': 'Test send failed',
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

const radioStub = {
  props: ['value'],
  emits: [],
  template: '<label class="arco-radio"><slot /></label>',
}

const radioGroupStub = {
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  template: '<div class="arco-radio-group"><slot /></div>',
}

const alertStub = {
  props: ['type'],
  template: '<div class="arco-alert" :class="type"><span class="alert-content"><slot /></span></div>',
}

const renderView = async (configs = {}) => {
  mocks.getSmsConfig.mockResolvedValue({
    provider: 'aliyun',
    access_key: 'AKID',
    access_secret: 'SECRET',
    sign_name: '平台',
    region: 'cn-hangzhou',
    sdk_app_id: '',
    verify_code_template: 'SMS_1',
    ...configs,
  })
  mocks.saveSmsConfig.mockImplementation(async (payload: Record<string, unknown>) => ({ ...payload }))
  mocks.testSmsSend.mockResolvedValue({ ok: true, detail: 'Sent OK' })

  const wrapper = mount(AdminSmsConfigView, {
    global: {
      stubs: {
        'a-radio': radioStub,
        'a-radio-group': radioGroupStub,
        'a-input': inputStub,
        'a-input-password': inputPasswordStub,
        'a-button': buttonStub,
        'a-alert': alertStub,
        'a-form': { template: '<form><slot /></form>' },
        'a-form-item': { template: '<div><slot /></div>' },
        'a-spin': { template: '<div><slot /></div>' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

const setProvider = async (wrapper: ReturnType<typeof renderView> extends Promise<infer T> ? T : never, value: string) => {
  wrapper.vm.form.provider = value
  await wrapper.vm.$nextTick()
}

describe('AdminSmsConfigView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads and backfills the form on mount', async () => {
    const wrapper = await renderView()
    const inputs = wrapper.findAll('input')

    expect(mocks.getSmsConfig).toHaveBeenCalled()
    expect(wrapper.vm.form.provider).toBe('aliyun')
    expect(inputs.some((input) => input.element.value === 'AKID')).toBe(true)
    expect(inputs.some((input) => input.element.value === 'SMS_1')).toBe(true)
  })

  it('saves the form via saveSmsConfig', async () => {
    const wrapper = await renderView()
    const saveButton = wrapper.findAll('button').find((button) => button.text() === 'Save')
    expect(saveButton).toBeTruthy()

    await saveButton!.trigger('click')
    await flushPromises()

    expect(mocks.saveSmsConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        provider: 'aliyun',
        access_key: 'AKID',
        region: 'cn-hangzhou',
      }),
    )
    expect(mocks.messageSuccess).toHaveBeenCalledWith('Saved')
  })

  it('renders successful test send result with detail', async () => {
    const wrapper = await renderView()
    const phoneInput = wrapper.findAll('input').find((input) => input.element.placeholder === 'test phone')
    expect(phoneInput).toBeTruthy()

    await phoneInput!.setValue('13800138000')
    const testButton = wrapper.findAll('button').find((button) => button.text() === 'Test send')
    expect(testButton).toBeTruthy()

    await testButton!.trigger('click')
    await flushPromises()

    expect(mocks.testSmsSend).toHaveBeenCalledWith('13800138000')
    const alert = wrapper.find('.arco-alert')
    expect(alert.classes()).toContain('success')
    expect(alert.find('.alert-content').text()).toBe('Sent OK')
  })

  it('renders failed test send result', async () => {
    const wrapper = await renderView()
    mocks.testSmsSend.mockResolvedValue({ ok: false, detail: 'isv.ERROR' })
    const phoneInput = wrapper.findAll('input').find((input) => input.element.placeholder === 'test phone')

    await phoneInput!.setValue('13800138000')
    const testButton = wrapper.findAll('button').find((button) => button.text() === 'Test send')
    await testButton!.trigger('click')
    await flushPromises()

    const alert = wrapper.find('.arco-alert')
    expect(alert.classes()).toContain('error')
    expect(alert.find('.alert-content').text()).toBe('isv.ERROR')
  })

  it('warns when test phone is empty', async () => {
    const wrapper = await renderView()
    const testButton = wrapper.findAll('button').find((button) => button.text() === 'Test send')

    await testButton!.trigger('click')
    await flushPromises()

    expect(mocks.testSmsSend).not.toHaveBeenCalled()
    expect(mocks.messageWarning).toHaveBeenCalledWith('Enter test phone')
  })

  it('blocks saving when provider enabled but required fields are missing', async () => {
    const wrapper = await renderView({ access_key: '' })
    await setProvider(wrapper, 'tencent')
    const saveButton = wrapper.findAll('button').find((button) => button.text() === 'Save')

    await saveButton!.trigger('click')
    await flushPromises()

    expect(mocks.saveSmsConfig).not.toHaveBeenCalled()
    expect(mocks.messageWarning).toHaveBeenCalledWith('Provider fields required')
  })

  it('allows saving when provider is not configured', async () => {
    const wrapper = await renderView({ provider: '' })
    const saveButton = wrapper.findAll('button').find((button) => button.text() === 'Save')

    await saveButton!.trigger('click')
    await flushPromises()

    expect(mocks.saveSmsConfig).toHaveBeenCalled()
  })
})
