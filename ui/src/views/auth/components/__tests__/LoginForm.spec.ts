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
        'IconYuxinAI': true,
        'icon-user': true,
        'icon-lock': true,
        'icon-email': true,
        'icon-safe': true,
        'icon-left': true,
        'icon-github': true,
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
