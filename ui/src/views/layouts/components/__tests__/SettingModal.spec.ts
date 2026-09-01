import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import SettingModal from '@/views/layouts/components/SettingModal.vue'

const mocks = vi.hoisted(() => ({
  account: {} as Record<string, unknown>,
  accountUpdate: vi.fn(),
  loadCurrentUser: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
  messageWarning: vi.fn(),
  messageInfo: vi.fn(),
  handleProvider: vi.fn(),
  sendBindPhoneCode: vi.fn(),
  bindPhone: vi.fn(),
  unbindPhone: vi.fn(),
  sendVerifyEmailCode: vi.fn(),
  verifyEmail: vi.fn(),
}))

const account = (overrides: Record<string, unknown> = {}) => ({
  id: 'account-1',
  name: 'tester',
  email: 'tester@example.com',
  email_verified: false,
  phone: '',
  phone_verified: false,
  avatar: '',
  last_login_ip: '',
  last_login_location: '',
  last_login_at: 0,
  created_at: 0,
  password_set: true,
  oauth_bindings: [],
  ...overrides,
})

const baseAccount = account()

vi.mock('@/stores/account', () => ({
  useAccountStore: () => ({
    account: mocks.account,
    update: mocks.accountUpdate,
  }),
}))

vi.mock('@/hooks/use-account', async () => {
  const { ref } = await import('vue')
  return {
    useGetCurrentUser: () => ({
      current_user: ref({}),
      loadCurrentUser: mocks.loadCurrentUser,
    }),
    useGetAccountLoginHistory: () => ({
      loading: ref(false),
      history_state: ref({ history: [], total: 0, current_page: 1, page_size: 5 }),
      loadAccountLoginHistory: vi.fn(),
    }),
    useGetAccountSessions: () => ({
      loading: ref(false),
      session_state: ref({ session_capable: false, current_session_id: null, sessions: [] }),
      loadAccountSessions: vi.fn(),
    }),
    useUpdateAvatar: () => ({ handleUpdateAvatar: vi.fn() }),
    useUpdateName: () => ({ handleUpdateName: vi.fn() }),
    useUpdatePassword: () => ({ handleUpdatePassword: vi.fn() }),
    useSendChangeEmailCode: () => ({ loading: ref(false), handleSendChangeEmailCode: vi.fn() }),
    useUpdateEmail: () => ({ loading: ref(false), handleUpdateEmail: vi.fn() }),
    useUnbindOAuth: () => ({ handleUnbindOAuth: vi.fn() }),
    useSendBindPhoneCode: () => ({
      loading: ref(false),
      handleSendBindPhoneCode: mocks.sendBindPhoneCode,
    }),
    useBindPhone: () => ({ loading: ref(false), handleBindPhone: mocks.bindPhone }),
    useUnbindPhone: () => ({ loading: ref(false), handleUnbindPhone: mocks.unbindPhone }),
    useSendVerifyEmailCode: () => ({
      loading: ref(false),
      handleSendVerifyEmailCode: mocks.sendVerifyEmailCode,
    }),
    useVerifyEmail: () => ({ loading: ref(false), handleVerifyEmail: mocks.verifyEmail }),
    useRevokeAccountSession: () => ({ handleRevokeAccountSession: vi.fn() }),
    useRevokeOtherAccountSessions: () => ({
      loading: ref(false),
      handleRevokeOtherAccountSessions: vi.fn(),
    }),
  }
})

vi.mock('@/hooks/use-upload-file', () => ({
  useUploadImage: () => ({
    image_url: { value: '' },
    handleUploadImage: vi.fn(),
  }),
}))

vi.mock('@/hooks/use-oauth', () => ({
  useProvider: () => ({
    redirect_url: { value: '' },
    handleProvider: mocks.handleProvider,
  }),
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    success: mocks.messageSuccess,
    error: mocks.messageError,
    warning: mocks.messageWarning,
    info: mocks.messageInfo,
  },
}))

const inputStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template:
    '<input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const buttonStub = {
  props: ['loading', 'disabled', 'type', 'status'],
  emits: ['click'],
  template:
    '<button type="button" :disabled="loading || disabled" @click="$emit(\'click\')"><slot /></button>',
}

const tagStub = {
  props: ['color'],
  template: '<span><slot /></span>',
}

const formStub = {
  template: '<div><slot /></div>',
}

const formItemStub = {
  props: ['field', 'label'],
  template: '<div><slot /></div>',
}

const inputPasswordStub = inputStub

const mountSecurityTab = async (accountData: Record<string, unknown>) => {
  mocks.account = accountData
  mocks.accountUpdate.mockClear()
  mocks.loadCurrentUser.mockResolvedValue(accountData)
  const wrapper = mount(SettingModal, {
    props: {
      visible: true,
      initialTab: 'security',
    },
    global: {
      stubs: {
        'a-modal': {
          template: '<div><slot /></div>',
        },
        'a-input': inputStub,
        'a-input-password': inputPasswordStub,
        'a-button': buttonStub,
        'a-tag': tagStub,
        'a-form': formStub,
        'a-form-item': formItemStub,
        'a-pagination': true,
        'a-select': true,
        'a-input-search': true,
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('SettingModal security tab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.account = baseAccount
  })

  it('renders masked phone and verified badge when phone is bound', async () => {
    const wrapper = await mountSecurityTab(account({ phone: '138****8000', phone_verified: true }))

    expect(wrapper.text()).toContain('138****8000')
    expect(wrapper.text()).toContain('已绑定')
    expect(wrapper.text()).toContain('解绑')
  })

  it('renders unbound phone state with bind button', async () => {
    const wrapper = await mountSecurityTab(baseAccount)

    expect(wrapper.text()).toContain('绑定手机号')
    expect(wrapper.text()).toContain('未绑定')
  })

  it('renders email verified badge when email is verified', async () => {
    const wrapper = await mountSecurityTab(account({ email_verified: true }))

    expect(wrapper.text()).toContain('已验证')
    expect(wrapper.text()).not.toContain('验证邮箱')
  })

  it('runs the bind phone flow', async () => {
    mocks.sendBindPhoneCode.mockResolvedValue({ message: '验证码已发送' })
    mocks.bindPhone.mockResolvedValue({ message: '手机号绑定成功' })
    mocks.loadCurrentUser.mockResolvedValue(
      account({ phone: '138****8000', phone_verified: true }),
    )
    const wrapper = await mountSecurityTab(baseAccount)

    await wrapper.findAll('button').find((b) => b.text() === '绑定手机号')!.trigger('click')
    await flushPromises()

    const phoneInput = wrapper
      .findAll('input')
      .find((i) => i.attributes('placeholder') === '请输入手机号')!
    await phoneInput.setValue('13800138000')

    await wrapper.findAll('button').find((b) => b.text() === '发送验证码')!.trigger('click')
    await flushPromises()
    expect(mocks.sendBindPhoneCode).toHaveBeenCalledWith('13800138000')

    const codeInput = wrapper
      .findAll('input')
      .find((i) => i.attributes('placeholder') === '请输入6位验证码')!
    await codeInput.setValue('123456')

    await wrapper.findAll('button').find((b) => b.text() === '确认绑定')!.trigger('click')
    await flushPromises()

    expect(mocks.bindPhone).toHaveBeenCalledWith('13800138000', '123456')
    expect(mocks.loadCurrentUser).toHaveBeenCalled()
    expect(mocks.accountUpdate).toHaveBeenCalled()
  })

  it('runs the unbind phone flow', async () => {
    mocks.unbindPhone.mockResolvedValue({ message: '手机号解绑成功' })
    mocks.loadCurrentUser.mockResolvedValue(baseAccount)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = await mountSecurityTab(account({ phone: '138****8000', phone_verified: true }))

    await wrapper.findAll('button').find((b) => b.text() === '解绑')!.trigger('click')
    await flushPromises()

    const codeInput = wrapper
      .findAll('input')
      .find((i) => i.attributes('placeholder') === '请输入6位验证码')!
    await codeInput.setValue('123456')

    const confirmButtons = wrapper.findAll('button').filter((b) => b.text() === '解绑')
    await confirmButtons[confirmButtons.length - 1].trigger('click')
    await flushPromises()

    expect(mocks.unbindPhone).toHaveBeenCalledWith('123456')
    expect(mocks.loadCurrentUser).toHaveBeenCalled()
  })

  it('runs the email verification flow', async () => {
    mocks.sendVerifyEmailCode.mockResolvedValue({ message: '验证码已发送' })
    mocks.verifyEmail.mockResolvedValue({ message: '邮箱验证成功' })
    mocks.loadCurrentUser.mockResolvedValue(account({ email_verified: true }))
    const wrapper = await mountSecurityTab(baseAccount)

    await wrapper.findAll('button').find((b) => b.text() === '验证邮箱')!.trigger('click')
    await flushPromises()

    await wrapper.findAll('button').find((b) => b.text() === '发送验证码')!.trigger('click')
    await flushPromises()
    expect(mocks.sendVerifyEmailCode).toHaveBeenCalled()

    const codeInput = wrapper
      .findAll('input')
      .find((i) => i.attributes('placeholder') === '请输入6位验证码')!
    await codeInput.setValue('123456')

    await wrapper.findAll('button').find((b) => b.text() === '确认验证')!.trigger('click')
    await flushPromises()

    expect(mocks.verifyEmail).toHaveBeenCalledWith('123456')
    expect(mocks.loadCurrentUser).toHaveBeenCalled()
    expect(mocks.accountUpdate).toHaveBeenCalled()
  })
})
