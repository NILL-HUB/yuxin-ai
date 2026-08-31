import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminMailConfigView from '@/views/admin/AdminMailConfigView.vue'

const mocks = vi.hoisted(() => ({
  getMailConfig: vi.fn(),
  saveMailConfig: vi.fn(),
  testMailSend: vi.fn(),
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
  messageWarning: vi.fn(),
}))

vi.mock('@/services/admin-message-config', () => ({
  getMailConfig: mocks.getMailConfig,
  saveMailConfig: mocks.saveMailConfig,
  testMailSend: mocks.testMailSend,
  getSmsConfig: vi.fn(),
  saveSmsConfig: vi.fn(),
  testSmsSend: vi.fn(),
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
        'admin.messageConfig.mail.title': 'Mail config',
        'admin.messageConfig.mail.description': 'Configure SMTP',
        'admin.messageConfig.mail.loadFailed': 'Load failed',
        'admin.messageConfig.mail.saved': 'Saved',
        'admin.messageConfig.mail.saveFailed': 'Save failed',
        'admin.messageConfig.mail.smtpHost': 'SMTP Host',
        'admin.messageConfig.mail.smtpHostRequired': 'SMTP host is required',
        'admin.messageConfig.mail.smtpHostPlaceholder': 'smtp.qq.com',
        'admin.messageConfig.mail.smtpPort': 'Port',
        'admin.messageConfig.mail.smtpPortRequired': 'Port is required',
        'admin.messageConfig.mail.security': 'Security',
        'admin.messageConfig.mail.useTls': 'TLS',
        'admin.messageConfig.mail.useSsl': 'SSL',
        'admin.messageConfig.mail.username': 'Username',
        'admin.messageConfig.mail.usernamePlaceholder': 'user',
        'admin.messageConfig.mail.password': 'Password',
        'admin.messageConfig.mail.passwordPlaceholder': 'auth code',
        'admin.messageConfig.mail.defaultSender': 'Sender',
        'admin.messageConfig.mail.defaultSenderPlaceholder': 'noreply@x.com',
        'admin.messageConfig.mail.fromName': 'From name',
        'admin.messageConfig.mail.timeout': 'Timeout',
        'admin.messageConfig.mail.save': 'Save',
        'admin.messageConfig.mail.testSend': 'Test send',
        'admin.messageConfig.mail.testToPlaceholder': 'recipient email',
        'admin.messageConfig.mail.testToRequired': 'Enter recipient email',
        'admin.messageConfig.mail.testSuccess': 'Sent',
        'admin.messageConfig.mail.testFailure': 'Send failed',
        'admin.messageConfig.mail.testFailed': 'Test send failed',
      })[key] ?? key,
  }),
}))

const switchStub = {
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  template: '<button type="button" class="arco-switch" :class="{ on: modelValue }" @click="$emit(\'change\', !modelValue)"></button>',
}

const inputStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template: '<input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const inputNumberStub = {
  props: ['modelValue', 'min', 'max'],
  emits: ['update:modelValue'],
  template: '<input type="number" class="arco-input-number" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
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

const alertStub = {
  props: ['type'],
  template: '<div class="arco-alert" :class="type"><span class="alert-content"><slot /></span></div>',
}

const renderView = async () => {
  mocks.getMailConfig.mockResolvedValue({
    smtp_host: 'smtp.qq.com',
    smtp_port: '587',
    use_tls: true,
    use_ssl: false,
    username: 'noreply@x.com',
    password: '',
    default_sender: 'noreply@x.com',
    from_name: 'Yuxin',
    timeout: '30',
  })
  mocks.saveMailConfig.mockImplementation(async (configs: Record<string, unknown>) => ({ ...configs }))
  mocks.testMailSend.mockResolvedValue({ ok: true, detail: 'Sent OK' })

  const wrapper = mount(AdminMailConfigView, {
    global: {
      stubs: {
        'a-switch': switchStub,
        'a-input': inputStub,
        'a-input-number': inputNumberStub,
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

describe('AdminMailConfigView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads and backfills the form on mount', async () => {
    const wrapper = await renderView()
    const inputs = wrapper.findAll('input')

    expect(mocks.getMailConfig).toHaveBeenCalled()
    expect(inputs.some((input) => input.element.value === 'smtp.qq.com')).toBe(true)
    expect(inputs.some((input) => input.element.value === 'noreply@x.com')).toBe(true)
    const switches = wrapper.findAll('.arco-switch')
    expect(switches[0].classes()).toContain('on')
    expect(switches[1].classes()).not.toContain('on')
  })

  it('saves the form via saveMailConfig', async () => {
    const wrapper = await renderView()
    const saveButton = wrapper.findAll('button').find((button) => button.text() === 'Save')
    expect(saveButton).toBeTruthy()

    await saveButton!.trigger('click')
    await flushPromises()

    expect(mocks.saveMailConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        smtp_host: 'smtp.qq.com',
        smtp_port: '587',
        use_tls: true,
        use_ssl: false,
      }),
    )
    expect(mocks.messageSuccess).toHaveBeenCalledWith('Saved')
  })

  it('renders successful test send result with detail', async () => {
    mocks.testMailSend.mockResolvedValue({ ok: true, detail: 'Sent OK' })
    const wrapper = await renderView()
    const emailInput = wrapper.findAll('input').find((input) => input.element.placeholder === 'recipient email')
    expect(emailInput).toBeTruthy()

    await emailInput!.setValue('ops@x.com')
    const testButton = wrapper.findAll('button').find((button) => button.text() === 'Test send')
    expect(testButton).toBeTruthy()

    await testButton!.trigger('click')
    await flushPromises()

    expect(mocks.testMailSend).toHaveBeenCalledWith('ops@x.com')
    const alert = wrapper.find('.arco-alert')
    expect(alert.classes()).toContain('success')
    expect(alert.find('.alert-content').text()).toBe('Sent OK')
  })

  it('renders failed test send result', async () => {
    const wrapper = await renderView()
    mocks.testMailSend.mockResolvedValue({ ok: false, detail: 'SMTP down' })
    const emailInput = wrapper.findAll('input').find((input) => input.element.placeholder === 'recipient email')

    await emailInput!.setValue('ops@x.com')
    const testButton = wrapper.findAll('button').find((button) => button.text() === 'Test send')
    await testButton!.trigger('click')
    await flushPromises()

    const alert = wrapper.find('.arco-alert')
    expect(alert.classes()).toContain('error')
    expect(alert.find('.alert-content').text()).toBe('SMTP down')
  })

  it('warns when test recipient is empty', async () => {
    const wrapper = await renderView()
    const testButton = wrapper.findAll('button').find((button) => button.text() === 'Test send')

    await testButton!.trigger('click')
    await flushPromises()

    expect(mocks.testMailSend).not.toHaveBeenCalled()
    expect(mocks.messageWarning).toHaveBeenCalledWith('Enter recipient email')
  })

  it('mutually toggles TLS and SSL switches with TLS priority', async () => {
    const wrapper = await renderView()
    const switches = wrapper.findAll('.arco-switch')
    const sslSwitch = switches[1]

    await sslSwitch.trigger('click')
    await flushPromises()

    expect(wrapper.vm.form.use_tls).toBe(false)
    expect(wrapper.vm.form.use_ssl).toBe(true)

    const tlsSwitch = wrapper.findAll('.arco-switch')[0]
    await tlsSwitch.trigger('click')
    await flushPromises()

    expect(wrapper.vm.form.use_tls).toBe(true)
    expect(wrapper.vm.form.use_ssl).toBe(false)
  })
})
