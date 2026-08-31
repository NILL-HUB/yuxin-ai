import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import LoginForm from '@/views/auth/components/LoginForm.vue'
import { createRequestError } from '@/utils/error'

const mocks = vi.hoisted(() => ({
  routerReplace: vi.fn(),
  credentialUpdate: vi.fn(),
  adminLogin: vi.fn(),
  passwordLogin: vi.fn(),
  directRegister: vi.fn(),
  prepareRegister: vi.fn(),
  verifyRegister: vi.fn(),
  logout: vi.fn(),
  sendResetCode: vi.fn(),
  resetPassword: vi.fn(),
  verifyLoginChallenge: vi.fn(),
  resendLoginChallenge: vi.fn(),
  getLoginMethods: vi.fn(),
  sendCode: vi.fn(),
  phoneCodeLogin: vi.fn(),
  emailCodeLogin: vi.fn(),
  phoneRegisterRequest: vi.fn(),
  phoneRegisterVerify: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
  messageWarning: vi.fn(),
  handleProvider: vi.fn(),
  routeQuery: {} as Record<string, string>,
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: mocks.routeQuery }),
  useRouter: () => ({
    replace: mocks.routerReplace,
  }),
}))

vi.mock('@/services/admin-auth', () => ({
  adminLogin: mocks.adminLogin,
}))

vi.mock('@/stores/credential', () => ({
  useCredentialStore: () => ({
    credential: {},
    update: mocks.credentialUpdate,
    clear: vi.fn(),
  }),
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    success: mocks.messageSuccess,
    error: mocks.messageError,
    warning: mocks.messageWarning,
  },
}))

vi.mock('@/services/auth', () => ({
  passwordLogin: mocks.passwordLogin,
  directRegister: mocks.directRegister,
  prepareRegister: mocks.prepareRegister,
  verifyRegister: mocks.verifyRegister,
  logout: mocks.logout,
  sendResetCode: mocks.sendResetCode,
  resetPassword: mocks.resetPassword,
  verifyLoginChallenge: mocks.verifyLoginChallenge,
  resendLoginChallenge: mocks.resendLoginChallenge,
  getLoginMethods: mocks.getLoginMethods,
  sendCode: mocks.sendCode,
  phoneCodeLogin: mocks.phoneCodeLogin,
  emailCodeLogin: mocks.emailCodeLogin,
  phoneRegisterRequest: mocks.phoneRegisterRequest,
  phoneRegisterVerify: mocks.phoneRegisterVerify,
}))

vi.mock('@/hooks/use-oauth', async () => {
  const { ref } = await import('vue')
  return {
    useProvider: () => ({
      loading: ref(false),
      redirect_url: ref(''),
      handleProvider: mocks.handleProvider,
    }),
  }
})

const formStub = {
  emits: ['submit'],
  template: '<form @submit.prevent="$emit(\'submit\', { errors: undefined })"><slot /></form>',
}

const formItemStub = {
  template: '<div><slot /></div>',
}

const inputStub = {
  props: ['modelValue', 'placeholder', 'readonly', 'maxlength'],
  emits: ['update:modelValue', 'keyup.enter'],
  template: `
    <label>
      <slot name="prefix" />
      <input
        :value="modelValue"
        :placeholder="placeholder"
        :readonly="readonly"
        :maxlength="maxlength"
        @input="$emit('update:modelValue', $event.target.value)"
        @keyup.enter="$emit('keyup.enter')"
      />
      <slot name="suffix" />
    </label>
  `,
}

const buttonStub = {
  props: ['disabled', 'loading'],
  emits: ['click'],
  template:
    '<button type="button" :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>',
}

const linkStub = {
  emits: ['click'],
  template: '<button type="button" @click="$emit(\'click\')"><slot /></button>',
}

const checkboxStub = {
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  template: `
    <input
      type="checkbox"
      :checked="modelValue"
      @change="$emit('update:modelValue', $event.target.checked); $emit('change', $event.target.checked)"
    />
  `,
}

const tabKeyByTitle: Record<string, string> = {
  密码登录: 'password',
  手机验证码: 'phone',
  邮箱验证码: 'email',
  账号密码: 'direct',
}

const tabsStub = {
  props: ['activeKey'],
  emits: ['change', 'update:activeKey'],
  template: `
    <div class="tabs-stub" data-testid="tabs" @click="onTabClick">
      <slot />
    </div>
  `,
  methods: {
    onTabClick(event: MouseEvent) {
      const target = (event.target as HTMLElement).closest('.tab-pane-stub')
      if (!target) return
      const title = target.getAttribute('data-title') || ''
      const key = tabKeyByTitle[title]
      if (!key) return
      this.$emit('change', key)
      this.$emit('update:activeKey', key)
    },
  },
}

const tabPaneStub = {
  props: ['title'],
  template: '<button type="button" class="tab-pane-stub" :data-title="title">{{ title }}</button>',
}

const renderForm = () => {
  return mount(LoginForm, {
    props: {
      embedded: true,
      redirectAfterLogin: false,
    },
    global: {
      stubs: {
        'a-form': formStub,
        'a-form-item': formItemStub,
        'a-input': inputStub,
        'a-input-password': inputStub,
        'a-button': buttonStub,
        'a-link': linkStub,
        'a-checkbox': checkboxStub,
        'a-tabs': tabsStub,
        'a-tab-pane': tabPaneStub,
        'IconYuxinAI': true,
        'icon-user': true,
        'icon-lock': true,
        'icon-email': true,
        'icon-safe': true,
        'icon-left': true,
        'icon-github': true,
        'icon-phone': true,
      },
    },
  })
}

const fillLoginForm = async (wrapper: ReturnType<typeof mount>, identifier: string, password: string) => {
  await wrapper.get('input[placeholder="用户名或邮箱"]').setValue(identifier)
  await wrapper.get('input[placeholder="账号密码"]').setValue(password)
}

const findButtonContainingText = (wrapper: ReturnType<typeof mount>, text: string) => {
  return wrapper.findAll('button').find((button) => button.text().includes(text))
}

const createAuthRequestError = (
  message: string,
  data: Record<string, unknown> = {},
  code = 'fail',
) => {
  return createRequestError({
    message,
    code,
    response: {
      code,
      message,
      data,
    },
  })
}

describe('LoginForm auto register flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    sessionStorage.clear()

    mocks.routeQuery = {}
    mocks.adminLogin.mockReset()
    mocks.passwordLogin.mockReset()
    mocks.directRegister.mockReset()
    mocks.prepareRegister.mockReset()
    mocks.sendResetCode.mockReset()
    mocks.getLoginMethods.mockResolvedValue({
      data: { email_enabled: true, phone_enabled: true, challenge_enabled: true },
      message: 'ok',
    })
    mocks.sendCode.mockResolvedValue({ message: '验证码已发送', data: {} })
    mocks.phoneCodeLogin.mockReset()
    mocks.emailCodeLogin.mockReset()
    mocks.phoneRegisterRequest.mockReset()
    mocks.phoneRegisterVerify.mockReset()
    mocks.verifyLoginChallenge.mockReset()
    mocks.resendLoginChallenge.mockReset()
  })

  it('emits success after embedded admin login so the login modal closes immediately', async () => {
    mocks.routeQuery = { mode: 'admin' }
    mocks.adminLogin.mockResolvedValue({ data: {}, message: 'ok' })

    const wrapper = renderForm()
    await fillLoginForm(wrapper, 'admin', 'Admin_123456')

    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(mocks.adminLogin).toHaveBeenCalledWith('admin', 'Admin_123456')
    expect(wrapper.emitted('success')).toHaveLength(1)
    expect(mocks.routerReplace).not.toHaveBeenCalled()
  })

  it('attempts auto-register but shows password required error when login fails with invalid credentials', async () => {
    mocks.passwordLogin.mockRejectedValue(
      createAuthRequestError('账号不存在或者密码错误', {
        reason_code: 'INVALID_CREDENTIALS',
      }),
    )

    const wrapper = renderForm()
    await fillLoginForm(wrapper, 'new-user@example.com', 'Abcd1234')

    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(mocks.passwordLogin).toHaveBeenCalledWith('new-user@example.com', 'Abcd1234')
    expect(mocks.directRegister).not.toHaveBeenCalled()
    expect(mocks.messageError).toHaveBeenCalledWith('请输入注册密码')
  })

  it('shows error message and stays on register view when direct register reports the account already exists', async () => {
    mocks.directRegister.mockRejectedValue(
      createAuthRequestError('账号已存在，请直接登录', {
        reason_code: 'ACCOUNT_EXISTS',
      }),
    )

    const wrapper = renderForm()
    await fillLoginForm(wrapper, 'existinguser', 'Abcd1234')

    const registerEntryButton = findButtonContainingText(wrapper, '用户名/邮箱注册')
    expect(registerEntryButton).toBeTruthy()

    await registerEntryButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('设置用户名并使用邮箱验证，完成后即可登录')

    const registerButton = findButtonContainingText(wrapper, '注册')
    expect(registerButton).toBeTruthy()

    await registerButton!.trigger('click')
    await flushPromises()

    expect(mocks.directRegister).toHaveBeenCalledWith('existinguser', 'Abcd1234')
    expect(wrapper.text()).toContain('账号已存在，请直接登录')
    expect(wrapper.text()).toContain('设置用户名并使用邮箱验证，完成后即可登录')
  })

  it('hides oauth-only provider suggestions when direct register falls back to an oauth-only account', async () => {
    mocks.directRegister.mockRejectedValue(
      createAuthRequestError('该账号尚未设置密码，请使用Google登录', {
        reason_code: 'OAUTH_ONLY_ACCOUNT',
        providers: ['google'],
      }),
    )

    const wrapper = renderForm()
    await fillLoginForm(wrapper, 'oauthuser', 'Abcd1234')

    const registerEntryButton = findButtonContainingText(wrapper, '用户名/邮箱注册')
    await registerEntryButton!.trigger('click')
    await flushPromises()

    const registerButton = findButtonContainingText(wrapper, '注册')
    await registerButton!.trigger('click')
    await flushPromises()

    expect(mocks.directRegister).toHaveBeenCalledWith('oauthuser', 'Abcd1234')
    expect(wrapper.text()).toContain('该账号尚未设置密码，请使用Google登录')
    expect(wrapper.find('[data-testid="oauth-only-suggestions"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Google 登录')
  })

  it('provides an explicit register entry that registers and finalizes login', async () => {
    mocks.directRegister.mockResolvedValue({
      data: { access_token: 'new-token', expire_at: 9999999999 },
    })

    const wrapper = renderForm()
    await fillLoginForm(wrapper, 'registeruser', 'Abcd1234')

    const registerEntryButton = findButtonContainingText(wrapper, '用户名/邮箱注册')
    expect(registerEntryButton).toBeTruthy()

    await registerEntryButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('设置用户名并使用邮箱验证，完成后即可登录')

    const registerButton = findButtonContainingText(wrapper, '注册')
    expect(registerButton).toBeTruthy()

    await registerButton!.trigger('click')
    await flushPromises()

    expect(mocks.directRegister).toHaveBeenCalledWith('registeruser', 'Abcd1234')
    expect(wrapper.emitted('success')).toHaveLength(1)
  })

  it('registers with username and relaxed password characters', async () => {
    mocks.directRegister.mockResolvedValue({
      data: { access_token: 'new-token', expire_at: 9999999999 },
    })

    const wrapper = renderForm()
    const registerEntryButton = findButtonContainingText(wrapper, '用户名/邮箱注册')
    expect(registerEntryButton).toBeTruthy()

    await registerEntryButton!.trigger('click')
    await flushPromises()

    await wrapper.get('input[placeholder="请输入用户名(大小写字母或数字)"]').setValue('AtlasUser1')
    await wrapper.get('input[placeholder="请设置密码(字母+数字，可含_和.，6-32位)"]').setValue('Abcd_1234.')

    const registerButton = findButtonContainingText(wrapper, '注册')
    expect(registerButton).toBeTruthy()

    await registerButton!.trigger('click')
    await flushPromises()

    expect(mocks.directRegister).toHaveBeenCalledWith('AtlasUser1', 'Abcd_1234.')
    expect(wrapper.emitted('success')).toHaveLength(1)
  })

  it('uses the generic forgot-password message and proceeds to the reset step', async () => {
    mocks.sendResetCode.mockResolvedValue({
      message: '如果该邮箱已注册，验证码已发送，请查收',
      data: {},
    })

    const wrapper = renderForm()
    const forgotButton = findButtonContainingText(wrapper, '忘记密码?')

    expect(forgotButton).toBeTruthy()

    await forgotButton!.trigger('click')
    await wrapper.get('input[placeholder="请输入邮箱"]').setValue('missing@example.com')

    const sendCodeButton = findButtonContainingText(wrapper, '发送验证码')
    expect(sendCodeButton).toBeTruthy()

    await sendCodeButton!.trigger('click')
    await flushPromises()

    expect(mocks.sendResetCode).toHaveBeenCalledWith('missing@example.com')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('如果该邮箱已注册，验证码已发送，请查收')
    expect(wrapper.text()).toContain('输入验证码并设置新密码')
    expect(wrapper.find('input[placeholder="请输入6位验证码"]').exists()).toBe(true)
  })
})

describe('LoginForm login tabs', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    sessionStorage.clear()

    mocks.routeQuery = {}
    mocks.getLoginMethods.mockResolvedValue({
      data: { email_enabled: true, phone_enabled: true, challenge_enabled: true },
      message: 'ok',
    })
    mocks.sendCode.mockResolvedValue({ message: '验证码已发送', data: {} })
    mocks.phoneCodeLogin.mockReset()
    mocks.emailCodeLogin.mockReset()
  })

  it('renders login tabs per login-methods and hides phone/email tabs when disabled', async () => {
    mocks.getLoginMethods.mockResolvedValue({
      data: { email_enabled: false, phone_enabled: false, challenge_enabled: true },
      message: 'ok',
    })

    const wrapper = renderForm()
    await flushPromises()

    expect(wrapper.find('input[placeholder="用户名或邮箱"]').exists()).toBe(true)
    expect(wrapper.findAll('.tab-pane-stub').some((el) => el.attributes('data-title')?.includes('手机'))).toBe(false)
    expect(wrapper.findAll('.tab-pane-stub').some((el) => el.attributes('data-title')?.includes('邮箱'))).toBe(false)
  })

  it('submits phone code login with the phone and code payload', async () => {
    mocks.phoneCodeLogin.mockResolvedValue({
      data: { access_token: 'phone-token', expire_at: 9999999999 },
    })

    const wrapper = renderForm()
    await flushPromises()

    const phoneTabTitle = wrapper.findAll('.tab-pane-stub').find((el) => el.attributes('data-title')?.includes('手机'))
    expect(phoneTabTitle).toBeTruthy()
    await phoneTabTitle!.trigger('click')
    await flushPromises()

    await wrapper.get('input[placeholder="请输入手机号"]').setValue('13800138000')
    await wrapper.get('input[placeholder="请输入6位验证码"]').setValue('123456')

    const loginButton = findButtonContainingText(wrapper, '手机号登录')
    expect(loginButton).toBeTruthy()
    await loginButton!.trigger('click')
    await flushPromises()

    expect(mocks.phoneCodeLogin).toHaveBeenCalledWith('13800138000', '123456')
    expect(wrapper.emitted('success')).toHaveLength(1)
  })

  it('sends a phone_login code via sendCode with scene and phone', async () => {
    const wrapper = renderForm()
    await flushPromises()

    const phoneTabTitle = wrapper.findAll('.tab-pane-stub').find((el) => el.attributes('data-title')?.includes('手机'))
    await phoneTabTitle!.trigger('click')
    await flushPromises()

    await wrapper.get('input[placeholder="请输入手机号"]').setValue('13800138000')

    const getCodeButton = wrapper.findAll('button').find((button) => button.text().includes('发送验证码'))
    expect(getCodeButton).toBeTruthy()
    await getCodeButton!.trigger('click')
    await flushPromises()

    expect(mocks.sendCode).toHaveBeenCalledWith({
      scene: 'phone_login',
      phone: '13800138000',
    })
    expect(mocks.messageSuccess).toHaveBeenCalled()
  })

  it('sends an email_login code via sendCode with scene and email', async () => {
    const wrapper = renderForm()
    await flushPromises()

    const emailTabTitle = wrapper.findAll('.tab-pane-stub').find((el) => el.attributes('data-title')?.includes('邮箱'))
    expect(emailTabTitle).toBeTruthy()
    await emailTabTitle!.trigger('click')
    await flushPromises()

    await wrapper.get('input[placeholder="请输入邮箱地址"]').setValue('a@example.com')

    const getCodeButton = wrapper.findAll('button').find((button) => button.text().includes('发送验证码'))
    expect(getCodeButton).toBeTruthy()
    await getCodeButton!.trigger('click')
    await flushPromises()

    expect(mocks.sendCode).toHaveBeenCalledWith({
      scene: 'email_login',
      email: 'a@example.com',
    })
  })

  it('submits email code login with the email and code payload', async () => {
    mocks.emailCodeLogin.mockResolvedValue({
      data: { access_token: 'email-token', expire_at: 9999999999 },
    })

    const wrapper = renderForm()
    await flushPromises()

    const emailTabTitle = wrapper.findAll('.tab-pane-stub').find((el) => el.attributes('data-title')?.includes('邮箱'))
    expect(emailTabTitle).toBeTruthy()
    await emailTabTitle!.trigger('click')
    await flushPromises()

    await wrapper.get('input[placeholder="请输入邮箱地址"]').setValue('b@example.com')
    await wrapper.get('input[placeholder="请输入6位验证码"]').setValue('654321')

    const loginButton = findButtonContainingText(wrapper, '邮箱登录')
    expect(loginButton).toBeTruthy()
    await loginButton!.trigger('click')
    await flushPromises()

    expect(mocks.emailCodeLogin).toHaveBeenCalledWith('b@example.com', '654321')
    expect(wrapper.emitted('success')).toHaveLength(1)
  })
})

describe('LoginForm phone registration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    sessionStorage.clear()

    mocks.routeQuery = {}
    mocks.getLoginMethods.mockResolvedValue({
      data: { email_enabled: true, phone_enabled: true, challenge_enabled: true },
      message: 'ok',
    })
    mocks.sendCode.mockResolvedValue({ message: '验证码已发送', data: {} })
    mocks.phoneRegisterRequest.mockReset()
    mocks.phoneRegisterVerify.mockReset()
  })

  it('requests a phone register code and verifies with username and password', async () => {
    mocks.phoneRegisterRequest.mockResolvedValue({ message: '验证码已发送', data: {} })
    mocks.phoneRegisterVerify.mockResolvedValue({
      data: { access_token: 'phone-reg-token', expire_at: 9999999999 },
    })

    const wrapper = renderForm()
    await flushPromises()

    const registerEntry = findButtonContainingText(wrapper, '用户名/邮箱注册')
    await registerEntry!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('设置用户名并使用邮箱验证')

    const phoneRegisterTab = wrapper.findAll('.tab-pane-stub').find((el) => el.attributes('data-title')?.includes('手机验证码'))
    expect(phoneRegisterTab).toBeTruthy()
    await phoneRegisterTab!.trigger('click')
    await flushPromises()

    await wrapper.get('input[placeholder="请输入手机号"]').setValue('13800138000')
    await wrapper.get('input[placeholder="用户名(选填，字母或数字)"]').setValue('PhoneUser')
    await wrapper.get('input[placeholder="设置密码(选填，字母+数字，6-32位)"]').setValue('Abcd1234')

    const getCodeButton = wrapper.findAll('button').find((button) => button.text().includes('发送验证码'))
    await getCodeButton!.trigger('click')
    await flushPromises()

    expect(mocks.phoneRegisterRequest).toHaveBeenCalledWith('13800138000')

    await wrapper.get('input[placeholder="请输入6位验证码"]').setValue('654321')

    const registerButton = findButtonContainingText(wrapper, '手机号注册')
    await registerButton!.trigger('click')
    await flushPromises()

    expect(mocks.phoneRegisterVerify).toHaveBeenCalledWith('13800138000', '654321', {
      username: 'PhoneUser',
      password: 'Abcd1234',
    })
    expect(wrapper.emitted('success')).toHaveLength(1)
  })
})

describe('LoginForm challenge flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    sessionStorage.clear()

    mocks.routeQuery = {}
    mocks.getLoginMethods.mockResolvedValue({
      data: { email_enabled: true, phone_enabled: true, challenge_enabled: true },
      message: 'ok',
    })
    mocks.sendCode.mockResolvedValue({ message: '验证码已发送', data: {} })
    mocks.passwordLogin.mockReset()
    mocks.verifyLoginChallenge.mockReset()
  })

  const submitPasswordLogin = async (wrapper: ReturnType<typeof mount>) => {
    await wrapper.get('input[placeholder="用户名或邮箱"]').setValue('user@example.com')
    await wrapper.get('input[placeholder="账号密码"]').setValue('Abcd1234')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
  }

  it('sends code automatically for a single-channel challenge', async () => {
    mocks.passwordLogin.mockResolvedValue({
      data: {
        challenge_required: true,
        challenge_id: 'challenge-1',
        channels: [{ type: 'email', masked: 'u***@example.com' }],
        risk_reason: 'new_ip',
      },
    })

    const wrapper = renderForm()
    await submitPasswordLogin(wrapper)

    expect(mocks.sendCode).toHaveBeenCalledWith({
      scene: 'login_challenge',
      challenge_id: 'challenge-1',
      channel: 'email',
    })
    expect(wrapper.text()).toContain('验证码已发送至 u***@example.com')
  })

  it('shows channel cards for a multi-channel challenge and sends code only after selection', async () => {
    mocks.passwordLogin.mockResolvedValue({
      data: {
        challenge_required: true,
        challenge_id: 'challenge-2',
        channels: [
          { type: 'email', masked: 'a***@example.com' },
          { type: 'phone', masked: '138****8000' },
        ],
        risk_reason: 'new_ip',
      },
    })

    const wrapper = renderForm()
    await submitPasswordLogin(wrapper)

    expect(wrapper.find('[data-testid="challenge-channel-select"]').exists()).toBe(true)
    expect(mocks.sendCode).not.toHaveBeenCalled()

    const phoneCard = wrapper
      .findAll('[data-testid="challenge-channel-select"] button')
      .find((button) => button.text().includes('138****8000'))
    expect(phoneCard).toBeTruthy()
    await phoneCard!.trigger('click')

    expect(mocks.sendCode).not.toHaveBeenCalled()

    const getCodeButton = wrapper.findAll('button').find((button) => button.text().includes('获取验证码'))
    expect(getCodeButton).toBeTruthy()
    await getCodeButton!.trigger('click')
    await flushPromises()

    expect(mocks.sendCode).toHaveBeenCalledWith({
      scene: 'login_challenge',
      challenge_id: 'challenge-2',
      channel: 'phone',
    })
  })

  it('submits verify with the selected channel and finalizes login', async () => {
    mocks.passwordLogin.mockResolvedValue({
      data: {
        challenge_required: true,
        challenge_id: 'challenge-3',
        channels: [{ type: 'phone', masked: '138****8000' }],
        risk_reason: 'new_ip',
      },
    })
    mocks.verifyLoginChallenge.mockResolvedValue({
      data: { access_token: 'challenge-token', expire_at: 9999999999 },
    })

    const wrapper = renderForm()
    await submitPasswordLogin(wrapper)

    expect(mocks.sendCode).toHaveBeenCalledWith({
      scene: 'login_challenge',
      challenge_id: 'challenge-3',
      channel: 'phone',
    })

    await wrapper.get('input[placeholder="请输入6位验证码"]').setValue('123456')
    const verifyButton = findButtonContainingText(wrapper, '完成登录验证')
    await verifyButton!.trigger('click')
    await flushPromises()

    expect(mocks.verifyLoginChallenge).toHaveBeenCalledWith('challenge-3', '123456', 'phone')
    expect(wrapper.emitted('success')).toHaveLength(1)
  })

  it('falls back to masked_email for legacy challenge responses', async () => {
    mocks.passwordLogin.mockResolvedValue({
      data: {
        challenge_required: true,
        challenge_id: 'challenge-legacy',
        masked_email: 'legacy***@example.com',
        risk_reason: 'new_ip',
      },
    })

    const wrapper = renderForm()
    await submitPasswordLogin(wrapper)

    expect(mocks.sendCode).toHaveBeenCalledWith({
      scene: 'login_challenge',
      challenge_id: 'challenge-legacy',
      channel: 'email',
    })
    expect(wrapper.text()).toContain('验证码已发送至 legacy***@example.com')
  })

  it('resends a challenge code via resendLoginChallenge and updates the masked target', async () => {
    vi.useFakeTimers()
    try {
      mocks.passwordLogin.mockResolvedValue({
        data: {
          challenge_required: true,
          challenge_id: 'challenge-resend',
          channels: [{ type: 'email', masked: 'u***@example.com' }],
          risk_reason: 'new_ip',
        },
      })
      mocks.resendLoginChallenge.mockResolvedValue({
        message: 'ok',
        data: { challenge_id: 'challenge-resend', channel: 'email', masked: 'n***@example.com' },
      })

      const wrapper = renderForm()
      await wrapper.get('input[placeholder="用户名或邮箱"]').setValue('user@example.com')
      await wrapper.get('input[placeholder="账号密码"]').setValue('Abcd1234')
      await wrapper.get('form').trigger('submit')
      await flushPromises()

      expect(mocks.sendCode).toHaveBeenCalledWith({
        scene: 'login_challenge',
        challenge_id: 'challenge-resend',
        channel: 'email',
      })

      await vi.advanceTimersByTimeAsync(60000)
      await flushPromises()

      const resendButton = wrapper.findAll('button').find((button) => button.text().includes('重发验证码'))
      expect(resendButton).toBeTruthy()
      await resendButton!.trigger('click')
      await flushPromises()

      expect(mocks.resendLoginChallenge).toHaveBeenCalledWith('challenge-resend', 'email')
      expect(wrapper.text()).toContain('验证码已发送至 n***@example.com')
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })
})
