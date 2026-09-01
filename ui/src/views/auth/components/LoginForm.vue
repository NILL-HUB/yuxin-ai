<script setup lang="ts">
import IconYuxinAI from '@/components/icons/IconYuxinAI.vue'
import {
    useDirectRegister,
    usePasswordLogin,
    usePrepareRegister,
    useRegisterInviteInfo,
    useVerifyLoginChallenge,
    useVerifyRegister,
} from '@/hooks/use-auth'
import { useProvider } from '@/hooks/use-oauth'
import { type LoginAuthorizationData, type LoginChallengeChannel } from '@/models/auth'
import { adminLogin } from '@/services/admin-auth'
import {
  emailCodeLogin,
  getLoginMethods,
  phoneCodeLogin,
  phoneRegisterRequest,
  phoneRegisterVerify,
  resendLoginChallenge,
  resetPassword,
  sendCode,
  sendResetCode,
} from '@/services/auth'
import { useCredentialStore } from '@/stores/credential'
import { getErrorMessage, getErrorReasonCode, getErrorResponseData } from '@/utils/error'
import { type ValidatedError, Message } from '@arco-design/web-vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

const { t } = useI18n()

type AuthView = 'login' | 'register' | 'registerVerify' | 'challenge' | 'forgot'
type LoginTab = 'password' | 'phone' | 'email'
type RegisterTab = 'direct' | 'email' | 'phone'
type LoginChallengeSource = 'password' | 'oauth'
type SupportedOauthProvider = 'github' | 'google'
type LoginChallengeState = {
  challenge_id: string
  challenge_type: string
  masked_email: string
  channels: LoginChallengeChannel[]
  selected_channel: string
  code_sent: boolean
  risk_reason: string
  source: LoginChallengeSource
}

type RegisterFormState = {
  username: string
  email: string
  password: string
  verify_code: string
  invite_code: string
}

const props = withDefaults(
  defineProps<{
    embedded?: boolean
    redirectAfterLogin?: boolean
  }>(),
  {
    embedded: false,
    redirectAfterLogin: true,
  },
)

const emits = defineEmits<{
  (event: 'success'): void
}>()

const STORAGE_KEY = 'login_credentials'
const LOGIN_CHALLENGE_STORAGE_KEY = 'pending_login_challenge'
// 后端返回的原始消息（用于匹配后端协议，非展示文案，不可国际化）
const BACKEND_GENERIC_CREDENTIAL_ERROR_MESSAGE = '账号不存在或者密码错误'
const BACKEND_LEGACY_ACCOUNT_NOT_FOUND_MESSAGE = '账号不存在'
const BACKEND_PASSWORD_ERROR_MESSAGE = '密码错误'
const REASON_INVALID_CREDENTIALS = 'INVALID_CREDENTIALS'
const REASON_OAUTH_ONLY_ACCOUNT = 'OAUTH_ONLY_ACCOUNT'
const STRONG_PASSWORD_REGEX = /^(?=.*[a-zA-Z])(?=.*\d)[A-Za-z\d._@#$%*!?-]{6,32}$/
const USERNAME_REGEX = /^[A-Za-z0-9]{3,32}$/
const SHOW_THIRD_PARTY_LOGIN = false
const OAUTH_PROVIDER_LABELS: Record<SupportedOauthProvider, string> = {
  github: 'GitHub',
  google: 'Google',
}
const AUTO_REGISTER_LOGIN_ERROR_MESSAGES = new Set([
  BACKEND_GENERIC_CREDENTIAL_ERROR_MESSAGE,
  BACKEND_LEGACY_ACCOUNT_NOT_FOUND_MESSAGE,
])
const CREDENTIAL_ERROR_BACKEND_MESSAGES = new Set([
  BACKEND_GENERIC_CREDENTIAL_ERROR_MESSAGE,
  BACKEND_PASSWORD_ERROR_MESSAGE,
])

const createEmptyChallenge = (): LoginChallengeState => ({
  challenge_id: '',
  challenge_type: '',
  masked_email: '',
  channels: [],
  selected_channel: '',
  code_sent: false,
  risk_reason: '',
  source: 'password',
})

const createEmptyRegisterForm = (): RegisterFormState => ({
  username: '',
  email: '',
  password: '',
  verify_code: '',
  invite_code: '',
})

const getInviteCodeFromRoute = () => {
  const invite = route.query.invite
  return typeof invite === 'string' ? invite.trim() : ''
}

const authView = ref<AuthView>('login')
const loginTab = ref<LoginTab>('password')
const registerTab = ref<RegisterTab>('direct')
const errorMessage = ref('')
const loginForm = ref({ identifier: '', password: '' })
const phoneLoginForm = ref({ phone: '', code: '' })
const emailLoginForm = ref({ email: '', code: '' })
const phoneRegisterForm = ref({ phone: '', code: '', username: '', password: '' })
const methods = ref<{ email_enabled: boolean; phone_enabled: boolean; challenge_enabled: boolean }>({
  email_enabled: true,
  phone_enabled: true,
  challenge_enabled: true,
})
const registerForm = ref<RegisterFormState>(createEmptyRegisterForm())
const inviteCodeLocked = ref(false)
const inviteInfo = ref<{ required: boolean; inviter_name: string } | null>(null)
const rememberPassword = ref(true)
const oauthOnlyProviders = ref<SupportedOauthProvider[]>([])
const forgotStep = ref<1 | 2>(1)
const forgotForm = ref({
  email: '',
  code: '',
  new_password: '',
  confirm_password: '',
})
const loginChallenge = ref<LoginChallengeState>(createEmptyChallenge())
const challengeCode = ref('')
const sendingCode = ref(false)
const resetting = ref(false)
const countdown = ref(0)
const countdownTimer = ref<number>()
const challengeCountdown = ref(0)
const challengeTimer = ref<number>()
const registerCountdown = ref(0)
const registerTimer = ref<number>()
const phoneLoginCountdown = ref(0)
const phoneLoginTimer = ref<number>()
const emailLoginCountdown = ref(0)
const emailLoginTimer = ref<number>()
const phoneRegisterCountdown = ref(0)
const phoneRegisterTimer = ref<number>()
const sendingPhoneLoginCode = ref(false)
const sendingEmailLoginCode = ref(false)
const sendingPhoneRegisterCode = ref(false)
const sendingChallengeCode = ref(false)
const credentialStore = useCredentialStore()
const route = useRoute()
const router = useRouter()
const { loading: passwordLoginLoading, authorization, handlePasswordLogin } = usePasswordLogin()
const { loading: directRegisterLoading, authorization: registerAuthorization, handleDirectRegister } = useDirectRegister()
const {
  loading: verifyLoginChallengeLoading,
  authorization: challengeAuthorization,
  handleVerifyLoginChallenge,
} = useVerifyLoginChallenge()
const { loading: registerInviteInfoLoading, handleQueryInviteInfo } = useRegisterInviteInfo()
const { handlePrepareRegister } = usePrepareRegister()
const { loading: verifyRegisterLoading, authorization: verifyRegisterAuthorization, handleVerifyRegister } = useVerifyRegister()
const { loading: providerLoading, redirect_url, handleProvider } = useProvider()
const phoneCodeLoginLoading = ref(false)
const emailCodeLoginLoading = ref(false)
const phoneRegisterVerifyLoading = ref(false)
const sendingRegisterCode = ref(false)
const countdownText = computed(() => {
  return countdown.value > 0
    ? t('common.actions.resendInSeconds', { count: countdown.value })
    : t('common.actions.sendCode')
})
const challengeGetCodeText = computed(() => {
  if (challengeCountdown.value > 0) {
    return t('common.actions.resendInSeconds', { count: challengeCountdown.value })
  }
  if (!loginChallenge.value.code_sent) {
    return t('login.getCode')
  }
  return t('login.resendCode')
})
const phoneLoginCountdownText = computed(() => {
  return phoneLoginCountdown.value > 0
    ? t('common.actions.resendInSeconds', { count: phoneLoginCountdown.value })
    : t('common.actions.sendCode')
})
const emailLoginCountdownText = computed(() => {
  return emailLoginCountdown.value > 0
    ? t('common.actions.resendInSeconds', { count: emailLoginCountdown.value })
    : t('common.actions.sendCode')
})
const phoneRegisterCountdownText = computed(() => {
  return phoneRegisterCountdown.value > 0
    ? t('common.actions.resendInSeconds', { count: phoneRegisterCountdown.value })
    : t('common.actions.sendCode')
})
const registerCountdownText = computed(() => {
  return registerCountdown.value > 0
    ? t('common.actions.resendInSeconds', { count: registerCountdown.value })
    : t('common.actions.sendCode')
})
const hasOauthOnlyProviders = computed(() => oauthOnlyProviders.value.length > 0)
const loginModeDescription = computed(() => t('login.loginSubtitle'))
const challengeDescription = computed(() => {
  const target = loginChallenge.value.masked_email || t('login.boundEmail')
  if (loginChallenge.value.risk_reason === 'new_ip') {
    return t('login.challengeNewIpHint', { email: target })
  }
  return t('login.challengeDefaultHint', { email: target })
})
const challengeVerificationHint = computed(() => {
  const selected = loginChallenge.value.channels.find(
    (channel) => channel.type === loginChallenge.value.selected_channel,
  )
  const masked = selected?.masked || ''
  if (masked) return t('login.verifyCodeSentTo', { masked })
  return t('login.verifyCodeSentToGeneric')
})
const registerEntryDescription = computed(() => t('login.registerEntryHint', { email: t('login.yourEmail') }))
const registerVerifyDescription = computed(() => {
  const email = loginForm.value.identifier.trim()
  if (email) return t('login.registerVerifyHint', { email })
  return t('login.registerVerifySubtitle')
})
const showPhoneLoginTab = computed(() => methods.value.phone_enabled)
const showEmailLoginTab = computed(() => methods.value.email_enabled)
const showPhoneRegisterTab = computed(() => methods.value.phone_enabled)
const showEmailRegisterTab = computed(() => methods.value.email_enabled)

const getUserFriendlyErrorMessage = (error: unknown, fallback: string) => {
  const rawMessage = getErrorMessage(error, fallback).trim()
  if (!rawMessage) return fallback

  const normalizedMessage = rawMessage.toLowerCase()
  if (
    normalizedMessage.includes('traceback') ||
    normalizedMessage.includes('exception') ||
    normalizedMessage.includes('stack')
  ) {
    return fallback
  }

  if (
    normalizedMessage.includes('network') ||
    normalizedMessage.includes('failed to fetch') ||
    normalizedMessage.includes('timeout')
  ) {
    return t('login.networkError')
  }

  return rawMessage
}

const normalizeOauthProviders = (providers: unknown): SupportedOauthProvider[] => {
  if (!Array.isArray(providers)) return []

  const normalizedProviders: SupportedOauthProvider[] = []
  providers.forEach((provider) => {
    const normalizedProvider = String(provider || '').trim().toLowerCase()
    if (normalizedProvider !== 'google' && normalizedProvider !== 'github') return
    if (normalizedProviders.includes(normalizedProvider)) return
    normalizedProviders.push(normalizedProvider)
  })

  return normalizedProviders
}

const extractOauthProvidersFromError = (error: unknown): SupportedOauthProvider[] => {
  const data = getErrorResponseData(error)
  if (!data) return []
  return normalizeOauthProviders(data.providers)
}

const clearOauthOnlyProviders = () => {
  oauthOnlyProviders.value = []
}

const shouldRenderOauthProvider = (provider: SupportedOauthProvider) => {
  return oauthOnlyProviders.value.includes(provider)
}

const persistPendingLoginChallenge = () => {
  sessionStorage.setItem(LOGIN_CHALLENGE_STORAGE_KEY, JSON.stringify(loginChallenge.value))
}

const clearPendingLoginChallenge = () => {
  sessionStorage.removeItem(LOGIN_CHALLENGE_STORAGE_KEY)
}

const startChallengeCountdown = () => {
  if (challengeTimer.value) {
    window.clearInterval(challengeTimer.value)
  }
  challengeCountdown.value = 60
  challengeTimer.value = window.setInterval(() => {
    challengeCountdown.value -= 1
    if (challengeCountdown.value <= 0) {
      if (challengeTimer.value) {
        window.clearInterval(challengeTimer.value)
        challengeTimer.value = undefined
      }
      challengeCountdown.value = 0
    }
  }, 1000)
}

const clearChallengeCountdown = () => {
  if (challengeTimer.value) {
    window.clearInterval(challengeTimer.value)
    challengeTimer.value = undefined
  }
  challengeCountdown.value = 0
}

const clearRegisterCountdown = () => {
  if (registerTimer.value) {
    window.clearInterval(registerTimer.value)
    registerTimer.value = undefined
  }
  registerCountdown.value = 0
}

const startCountdown = (
  count: { value: number },
  timer: { value: number | undefined },
) => {
  if (timer.value) {
    window.clearInterval(timer.value)
  }
  count.value = 60
  timer.value = window.setInterval(() => {
    count.value -= 1
    if (count.value <= 0) {
      if (timer.value) {
        window.clearInterval(timer.value)
        timer.value = undefined
      }
      count.value = 0
    }
  }, 1000)
}

const clearPhoneLoginCountdown = () => {
  if (phoneLoginTimer.value) {
    window.clearInterval(phoneLoginTimer.value)
    phoneLoginTimer.value = undefined
  }
  phoneLoginCountdown.value = 0
}

const clearEmailLoginCountdown = () => {
  if (emailLoginTimer.value) {
    window.clearInterval(emailLoginTimer.value)
    emailLoginTimer.value = undefined
  }
  emailLoginCountdown.value = 0
}

const clearPhoneRegisterCountdown = () => {
  if (phoneRegisterTimer.value) {
    window.clearInterval(phoneRegisterTimer.value)
    phoneRegisterTimer.value = undefined
  }
  phoneRegisterCountdown.value = 0
}

const normalizeChallengeChannels = (payload: LoginAuthorizationData): LoginChallengeChannel[] => {
  if (Array.isArray(payload.channels) && payload.channels.length > 0) {
    return payload.channels
      .filter((channel) => channel && (channel.type === 'email' || channel.type === 'phone'))
      .map((channel) => ({
        type: channel.type,
        masked: String(channel.masked || ''),
        email: channel.email ? String(channel.email) : undefined,
        phone: channel.phone ? String(channel.phone) : undefined,
      }))
  }
  if (payload.masked_email) {
    return [{ type: 'email', masked: String(payload.masked_email) }]
  }
  return []
}

const applyLoginChallenge = (
  payload: LoginAuthorizationData,
  source: LoginChallengeSource = 'password',
) => {
  clearOauthOnlyProviders()
  const channels = normalizeChallengeChannels(payload)
  loginChallenge.value = {
    challenge_id: String(payload.challenge_id || ''),
    challenge_type: String(payload.challenge_type || 'email_code'),
    masked_email: String(payload.masked_email || ''),
    channels,
    selected_channel: channels.length === 1 ? channels[0].type : '',
    code_sent: false,
    risk_reason: String(payload.risk_reason || ''),
    source,
  }
  challengeCode.value = ''
  errorMessage.value = ''
  authView.value = 'challenge'
  persistPendingLoginChallenge()
  if (channels.length === 1) {
    void handleSendChallengeCode(channels[0].type)
  } else {
    clearChallengeCountdown()
  }
}

const clearLoginChallenge = () => {
  loginChallenge.value = createEmptyChallenge()
  challengeCode.value = ''
  clearChallengeCountdown()
  clearPendingLoginChallenge()
}

const applyRegisterDraft = (identifier: string, password: string) => {
  registerForm.value = {
    username: identifier.trim(),
    email: registerForm.value.email || (validateEmail(identifier.trim()) ? identifier.trim() : ''),
    password,
    verify_code: '',
    invite_code: registerForm.value.invite_code || getInviteCodeFromRoute(),
  }
}

const initInviteCode = async () => {
  const code = getInviteCodeFromRoute()
  if (!code) return
  inviteCodeLocked.value = true
  registerForm.value.invite_code = code
  try {
    const info = await handleQueryInviteInfo(code)
    if (info) {
      inviteInfo.value = { required: info.required, inviter_name: info.inviter_name || '' }
    }
  } catch {
    inviteInfo.value = null
  }
}

const enterRegisterView = (
  email: string,
  password: string,
  options: {
    preserveError?: boolean
  } = {},
) => {
  applyRegisterDraft(email, password)
  registerTab.value = 'direct'
  clearRegisterCountdown()
  clearLoginChallenge()
  resetForgotForm()
  if (!options.preserveError) {
    errorMessage.value = ''
  }
  authView.value = 'register'
}

const resetRegisterForm = () => {
  registerForm.value = createEmptyRegisterForm()
  clearRegisterCountdown()
}

const loadSavedCredentials = () => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (!saved) return
    const { identifier, email, password } = JSON.parse(saved)
    loginForm.value.identifier = identifier || email || ''
    loginForm.value.password = password || ''
    rememberPassword.value = true
  } catch {
    localStorage.removeItem(STORAGE_KEY)
  }
}

const loadPendingLoginChallenge = () => {
  try {
    const saved = sessionStorage.getItem(LOGIN_CHALLENGE_STORAGE_KEY)
    if (!saved) return
    const parsed = JSON.parse(saved)
    if (!parsed?.challenge_id) {
      clearPendingLoginChallenge()
      return
    }
    const channels = normalizeChallengeChannels(parsed as LoginAuthorizationData)
    loginChallenge.value = {
      challenge_id: String(parsed.challenge_id || ''),
      challenge_type: String(parsed.challenge_type || 'email_code'),
      masked_email: String(parsed.masked_email || ''),
      channels,
      selected_channel: channels.length === 1 ? channels[0].type : String(parsed.selected_channel || ''),
      code_sent: Boolean(parsed.code_sent),
      risk_reason: String(parsed.risk_reason || ''),
      source: parsed.source === 'oauth' ? 'oauth' : 'password',
    }
    authView.value = 'challenge'
    if (channels.length === 1 && !loginChallenge.value.code_sent) {
      void handleSendChallengeCode(channels[0].type)
    } else {
      startChallengeCountdown()
    }
  } catch {
    clearPendingLoginChallenge()
  }
}

const saveCredentials = (
  credentials: {
    identifier: string
    password: string
  } = loginForm.value,
) => {
  if (rememberPassword.value) {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        identifier: credentials.identifier,
        password: credentials.password,
      }),
    )
    return
  }
  localStorage.removeItem(STORAGE_KEY)
}

const handleRememberChange = (value: boolean | (string | number | boolean)[]) => {
  const checked = value as boolean
  if (!checked) localStorage.removeItem(STORAGE_KEY)
}

onMounted(() => {
  loadLoginMethods()
  loadSavedCredentials()
  loadPendingLoginChallenge()
  initInviteCode()
})

onBeforeUnmount(() => {
  if (countdownTimer.value) {
    window.clearInterval(countdownTimer.value)
  }
  clearChallengeCountdown()
  clearRegisterCountdown()
  clearPhoneLoginCountdown()
  clearEmailLoginCountdown()
  clearPhoneRegisterCountdown()
})

const loadLoginMethods = async () => {
  try {
    const resp = await getLoginMethods()
    const data = resp.data
    if (!data) return
    methods.value = {
      email_enabled: Boolean(data.email_enabled),
      phone_enabled: Boolean(data.phone_enabled),
      challenge_enabled: Boolean(data.challenge_enabled),
    }
    if (!methods.value.phone_enabled && loginTab.value === 'phone') {
      loginTab.value = 'password'
    }
    if (!methods.value.email_enabled && loginTab.value === 'email') {
      loginTab.value = 'password'
    }
    if (!methods.value.phone_enabled && registerTab.value === 'phone') {
      registerTab.value = 'direct'
    }
    if (!methods.value.email_enabled && registerTab.value === 'email') {
      registerTab.value = 'direct'
    }
  } catch {
    methods.value = { email_enabled: true, phone_enabled: true, challenge_enabled: true }
  }
}

const clearCountdown = () => {
  if (countdownTimer.value) {
    window.clearInterval(countdownTimer.value)
    countdownTimer.value = undefined
  }
  countdown.value = 0
}

const resetForgotForm = () => {
  forgotStep.value = 1
  forgotForm.value.code = ''
  forgotForm.value.new_password = ''
  forgotForm.value.confirm_password = ''
  clearCountdown()
}

const openForgotPassword = () => {
  errorMessage.value = ''
  clearOauthOnlyProviders()
  authView.value = 'forgot'
  forgotForm.value.email = validateEmail(loginForm.value.identifier.trim()) ? loginForm.value.identifier.trim() : ''
  resetForgotForm()
}

const openRegister = () => {
  clearOauthOnlyProviders()
  enterRegisterView(loginForm.value.identifier, loginForm.value.password)
}

const backToLogin = () => {
  if (authView.value === 'register') {
    loginForm.value.identifier = registerForm.value.username
    loginForm.value.password = registerForm.value.password
  }
  errorMessage.value = ''
  clearOauthOnlyProviders()
  authView.value = 'login'
  resetForgotForm()
  resetRegisterForm()
  clearLoginChallenge()
}

const handleLoginTabChange = (tab: string | number) => {
  const next = tab as LoginTab
  errorMessage.value = ''
  loginTab.value = next
}

const handleRegisterTabChange = (tab: string | number) => {
  const next = tab as RegisterTab
  errorMessage.value = ''
  registerTab.value = next
}

const handleForgotBack = () => {
  if (forgotStep.value === 2) {
    forgotStep.value = 1
    return
  }
  backToLogin()
}

const validateEmail = (email: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)

const handleSendCode = async () => {
  const email = forgotForm.value.email.trim()
  if (!email) {
    Message.error(t('login.emailRequired'))
    return
  }

  if (!validateEmail(email)) {
    Message.error(t('login.emailInvalid'))
    return
  }

  try {
    sendingCode.value = true
    const resp = await sendResetCode(email)
    Message.success(resp.message || t('login.resetCodeSent'))
    forgotStep.value = 2

    clearCountdown()
    countdown.value = 60
    countdownTimer.value = window.setInterval(() => {
      countdown.value -= 1
      if (countdown.value <= 0) {
        clearCountdown()
      }
    }, 1000)
  } catch (error: unknown) {
    Message.error(getUserFriendlyErrorMessage(error, t('login.sendCodeFailed')))
  } finally {
    sendingCode.value = false
  }
}

const handleResendCode = async () => {
  if (countdown.value > 0) return
  await handleSendCode()
}

const finalizeLoginSuccess = async (credential: LoginAuthorizationData) => {
  clearPendingLoginChallenge()
  clearOauthOnlyProviders()
  credentialStore.update({
    access_token: String(credential.access_token || ''),
    expire_at: Number(credential.expire_at || 0),
  })

  if (props.redirectAfterLogin) {
    Message.success(t('login.loginSuccessRedirecting'))
    await router.replace({ path: '/home' })
    return
  }

  Message.success(t('login.loginSuccess'))
  emits('success')
}

const handleVerifyChallenge = async () => {
  if (!loginChallenge.value.challenge_id) {
    errorMessage.value = t('login.challengeExpired')
    backToLogin()
    return
  }

  if (!challengeCode.value.trim()) {
    Message.error(t('login.codeRequired'))
    return
  }

  const channel = loginChallenge.value.selected_channel || loginChallenge.value.channels[0]?.type || ''

  try {
    await handleVerifyLoginChallenge(
      loginChallenge.value.challenge_id,
      challengeCode.value.trim(),
      channel,
    )
    const loginResult = challengeAuthorization.value
    if (loginChallenge.value.source === 'password') {
      saveCredentials()
    }
    clearLoginChallenge()
    await finalizeLoginSuccess(loginResult)
  } catch (error: unknown) {
    errorMessage.value = getUserFriendlyErrorMessage(error, t('login.challengeFailed'))
  }
}

const handleSendChallengeCode = async (channel: string) => {
  if (!loginChallenge.value.challenge_id || !channel) return
  if (challengeCountdown.value > 0 && loginChallenge.value.code_sent) return

  try {
    sendingChallengeCode.value = true
    await sendCode({
      scene: 'login_challenge',
      challenge_id: loginChallenge.value.challenge_id,
      channel,
    })
    loginChallenge.value.selected_channel = channel
    loginChallenge.value.code_sent = true
    errorMessage.value = ''
    startChallengeCountdown()
    persistPendingLoginChallenge()
  } catch (error: unknown) {
    errorMessage.value = getUserFriendlyErrorMessage(error, t('login.sendCodeFailed'))
  } finally {
    sendingChallengeCode.value = false
  }
}

const handleResendChallengeCode = async () => {
  const channel = loginChallenge.value.selected_channel || loginChallenge.value.channels[0]?.type
  if (!loginChallenge.value.challenge_id || !channel) return
  if (challengeCountdown.value > 0) return

  try {
    sendingChallengeCode.value = true
    const resp = await resendLoginChallenge(loginChallenge.value.challenge_id, channel)
    const masked = resp.data?.masked
    if (masked) {
      const channelIndex = loginChallenge.value.channels.findIndex((item) => item.type === channel)
      if (channelIndex >= 0) {
        loginChallenge.value.channels[channelIndex].masked = masked
      }
    }
    loginChallenge.value.code_sent = true
    errorMessage.value = ''
    startChallengeCountdown()
    persistPendingLoginChallenge()
  } catch (error: unknown) {
    errorMessage.value = getUserFriendlyErrorMessage(error, t('login.sendCodeFailed'))
  } finally {
    sendingChallengeCode.value = false
  }
}

const handleRequestChallengeCode = async () => {
  if (loginChallenge.value.code_sent) {
    await handleResendChallengeCode()
    return
  }
  const channel = loginChallenge.value.selected_channel || loginChallenge.value.channels[0]?.type
  if (channel) {
    await handleSendChallengeCode(channel)
  }
}

const handleSelectChallengeChannel = (channel: string) => {
  loginChallenge.value.selected_channel = channel
  loginChallenge.value.code_sent = false
  challengeCode.value = ''
  errorMessage.value = ''
  clearChallengeCountdown()
  persistPendingLoginChallenge()
}

const handleSendPhoneLoginCode = async () => {
  const phone = phoneLoginForm.value.phone.trim()
  if (!phone) {
    Message.error(t('login.phoneRequired'))
    return
  }

  try {
    sendingPhoneLoginCode.value = true
    const resp = await sendCode({ scene: 'phone_login', phone })
    Message.success(resp.message || t('login.codeSent'))
    startCountdown(phoneLoginCountdown, phoneLoginTimer)
  } catch (error: unknown) {
    Message.error(getUserFriendlyErrorMessage(error, t('login.sendCodeFailed')))
  } finally {
    sendingPhoneLoginCode.value = false
  }
}

const handlePhoneCodeLogin = async () => {
  const phone = phoneLoginForm.value.phone.trim()
  const code = phoneLoginForm.value.code.trim()

  if (!phone) {
    Message.error(t('login.phoneRequired'))
    return
  }

  if (!code) {
    Message.error(t('login.codeRequired'))
    return
  }

  try {
    errorMessage.value = ''
    phoneCodeLoginLoading.value = true
    const resp = await phoneCodeLogin(phone, code)
    const loginResult = resp.data
    if (loginResult.challenge_required) {
      applyLoginChallenge(loginResult, 'password')
      Message.warning(t('login.newLoginEnvironmentWarning'))
      return
    }
    saveCredentials({
      identifier: phone,
      password: '',
    })
    await finalizeLoginSuccess(loginResult)
  } catch (error: unknown) {
    errorMessage.value = getUserFriendlyErrorMessage(error, t('login.loginFailed'))
  } finally {
    phoneCodeLoginLoading.value = false
  }
}

const handleSendEmailLoginCode = async () => {
  const email = emailLoginForm.value.email.trim()
  if (!email) {
    Message.error(t('login.emailRequired'))
    return
  }

  if (!validateEmail(email)) {
    Message.error(t('login.emailInvalid'))
    return
  }

  try {
    sendingEmailLoginCode.value = true
    const resp = await sendCode({ scene: 'email_login', email })
    Message.success(resp.message || t('login.codeSent'))
    startCountdown(emailLoginCountdown, emailLoginTimer)
  } catch (error: unknown) {
    Message.error(getUserFriendlyErrorMessage(error, t('login.sendCodeFailed')))
  } finally {
    sendingEmailLoginCode.value = false
  }
}

const handleEmailCodeLogin = async () => {
  const email = emailLoginForm.value.email.trim()
  const code = emailLoginForm.value.code.trim()

  if (!email) {
    Message.error(t('login.emailRequired'))
    return
  }

  if (!code) {
    Message.error(t('login.codeRequired'))
    return
  }

  try {
    errorMessage.value = ''
    emailCodeLoginLoading.value = true
    const resp = await emailCodeLogin(email, code)
    const loginResult = resp.data
    if (loginResult.challenge_required) {
      applyLoginChallenge(loginResult, 'password')
      Message.warning(t('login.newLoginEnvironmentWarning'))
      return
    }
    saveCredentials({
      identifier: email,
      password: '',
    })
    await finalizeLoginSuccess(loginResult)
  } catch (error: unknown) {
    errorMessage.value = getUserFriendlyErrorMessage(error, t('login.loginFailed'))
  } finally {
    emailCodeLoginLoading.value = false
  }
}

const handleSendPhoneRegisterCode = async () => {
  const phone = phoneRegisterForm.value.phone.trim()
  if (!phone) {
    Message.error(t('login.phoneRequired'))
    return
  }

  try {
    sendingPhoneRegisterCode.value = true
    const resp = await phoneRegisterRequest(phone)
    Message.success(resp.message || t('login.codeSent'))
    startCountdown(phoneRegisterCountdown, phoneRegisterTimer)
  } catch (error: unknown) {
    Message.error(getUserFriendlyErrorMessage(error, t('login.sendCodeFailed')))
  } finally {
    sendingPhoneRegisterCode.value = false
  }
}

const handlePhoneRegisterVerify = async () => {
  const phone = phoneRegisterForm.value.phone.trim()
  const code = phoneRegisterForm.value.code.trim()
  const username = phoneRegisterForm.value.username.trim()
  const password = phoneRegisterForm.value.password

  if (!phone) {
    Message.error(t('login.phoneRequired'))
    return
  }

  if (!code) {
    Message.error(t('login.codeRequired'))
    return
  }

  if (username && !USERNAME_REGEX.test(username)) {
    Message.error(t('login.usernameRule'))
    return
  }

  if (password && !STRONG_PASSWORD_REGEX.test(password)) {
    Message.error(t('login.strongPasswordRule'))
    return
  }

  try {
    errorMessage.value = ''
    phoneRegisterVerifyLoading.value = true
    const resp = await phoneRegisterVerify(phone, code, {
      username: username || undefined,
      password: password || undefined,
    })
    const loginResult = resp.data
    if (password) {
      saveCredentials({
        identifier: username || phone,
        password,
      })
    }
    await finalizeLoginSuccess(loginResult)
  } catch (error: unknown) {
    errorMessage.value = getUserFriendlyErrorMessage(error, t('login.registerFailed'))
  } finally {
    phoneRegisterVerifyLoading.value = false
  }
}

const handleStartEmailRegister = async () => {
  const email = registerForm.value.email.trim()
  const password = registerForm.value.password

  if (!email) {
    Message.error(t('login.emailRequired'))
    return
  }

  if (!validateEmail(email)) {
    Message.error(t('login.emailInvalid'))
    return
  }

  if (!password) {
    Message.error(t('login.registerPasswordRequired'))
    return
  }

  if (!STRONG_PASSWORD_REGEX.test(password)) {
    Message.error(t('login.strongPasswordRule'))
    return
  }

  try {
    sendingRegisterCode.value = true
    const resp = await handlePrepareRegister(
      registerForm.value.username.trim(),
      email,
      password,
      registerForm.value.invite_code.trim(),
    )
    Message.success(resp.message || t('login.registerCodeSent'))
    registerForm.value.email = email
    registerForm.value.username = registerForm.value.username.trim()
    clearRegisterCountdown()
    startCountdown(registerCountdown, registerTimer)
  } catch (error: unknown) {
    Message.error(getUserFriendlyErrorMessage(error, t('login.sendCodeFailed')))
  } finally {
    sendingRegisterCode.value = false
  }
}

const handleVerifyEmailRegister = async () => {
  const email = registerForm.value.email.trim()
  const code = registerForm.value.verify_code.trim()
  const password = registerForm.value.password

  if (!email) {
    Message.error(t('login.emailRequired'))
    return
  }

  if (!code) {
    Message.error(t('login.codeRequired'))
    return
  }

  if (!password) {
    Message.error(t('login.registerPasswordRequired'))
    return
  }

  if (!STRONG_PASSWORD_REGEX.test(password)) {
    Message.error(t('login.strongPasswordRule'))
    return
  }

  try {
    errorMessage.value = ''
    await handleVerifyRegister(
      registerForm.value.username.trim(),
      email,
      password,
      code,
      registerForm.value.invite_code.trim(),
    )
    const loginResult = verifyRegisterAuthorization.value
    saveCredentials({
      identifier: registerForm.value.username.trim() || email,
      password,
    })
    await finalizeLoginSuccess(loginResult)
  } catch (error: unknown) {
    errorMessage.value = getUserFriendlyErrorMessage(error, t('login.registerFailed'))
  }
}

const handleStartRegister = async () => {
  const username = registerForm.value.username.trim()
  const password = registerForm.value.password

  if (username && !USERNAME_REGEX.test(username)) {
    Message.error(t('login.usernameRule'))
    return
  }

  if (!password) {
    Message.error(t('login.registerPasswordRequired'))
    return
  }

  if (!STRONG_PASSWORD_REGEX.test(password)) {
    Message.error(t('login.strongPasswordRule'))
    return
  }

  errorMessage.value = ''

  try {
    clearOauthOnlyProviders()
    await handleDirectRegister(username, password, registerForm.value.invite_code.trim())
    saveCredentials({
      identifier: username,
      password,
    })
    const loginResult = registerAuthorization.value
    await finalizeLoginSuccess(loginResult)
  } catch (error: unknown) {
    const message = getUserFriendlyErrorMessage(error, t('login.registerFailed'))
    const reasonCode = getErrorReasonCode(error)
    const providers = reasonCode === REASON_OAUTH_ONLY_ACCOUNT ? extractOauthProvidersFromError(error) : []
    if (reasonCode === REASON_OAUTH_ONLY_ACCOUNT) {
      oauthOnlyProviders.value = providers
    } else {
      clearOauthOnlyProviders()
    }
    errorMessage.value = message
  }
}

const handleResetPassword = async () => {
  if (!forgotForm.value.code) {
    Message.error(t('login.codeRequired'))
    return
  }

  if (!forgotForm.value.new_password) {
    Message.error(t('login.newPasswordRequired'))
    return
  }

  if (forgotForm.value.new_password !== forgotForm.value.confirm_password) {
    Message.error(t('login.passwordMismatch'))
    return
  }

  if (!STRONG_PASSWORD_REGEX.test(forgotForm.value.new_password)) {
    Message.error(t('login.strongPasswordRule'))
    return
  }

  try {
    resetting.value = true
    await resetPassword(
      forgotForm.value.email.trim(),
      forgotForm.value.code.trim(),
      forgotForm.value.new_password,
    )
    Message.success(t('login.resetPasswordSuccess'))
    loginForm.value.identifier = forgotForm.value.email.trim()
    loginForm.value.password = ''
    backToLogin()
  } catch (error: unknown) {
    Message.error(getUserFriendlyErrorMessage(error, t('login.resetPasswordFailed')))
  } finally {
    resetting.value = false
  }
}

const githubLogin = async () => {
  await handleProvider('github')
  window.location.href = redirect_url.value
}

const googleLogin = async () => {
  await handleProvider('google')
  window.location.href = redirect_url.value
}

const handleSubmit = async ({ errors }: { errors: Record<string, ValidatedError> | undefined }) => {
  if (errors) return

  if (route.query.mode === 'admin') {
    try {
      errorMessage.value = ''
      await adminLogin(loginForm.value.identifier.trim(), loginForm.value.password)
      Message.success(t('login.loginSuccess'))
      emits('success')
    } catch (error: unknown) {
      errorMessage.value = getUserFriendlyErrorMessage(error, t('login.loginFailed'))
      loginForm.value.password = ''
    }
    return
  }

  try {
    errorMessage.value = ''
    clearOauthOnlyProviders()
    await handlePasswordLogin(loginForm.value.identifier.trim(), loginForm.value.password)
    const loginResult = authorization.value

    if (loginResult.challenge_required) {
      applyLoginChallenge(loginResult, 'password')
      Message.warning(t('login.newLoginEnvironmentWarning'))
      return
    }

    saveCredentials()
    await finalizeLoginSuccess(loginResult)
  } catch (error: unknown) {
    const message = getUserFriendlyErrorMessage(error, t('login.loginFailed'))
    const reasonCode = getErrorReasonCode(error)
    const shouldAutoRegister =
      reasonCode === REASON_INVALID_CREDENTIALS ||
      (reasonCode === null && AUTO_REGISTER_LOGIN_ERROR_MESSAGES.has(message))

    if (shouldAutoRegister) {
      await handleStartRegister()
      return
    }

    errorMessage.value = message
    if (reasonCode === REASON_INVALID_CREDENTIALS || CREDENTIAL_ERROR_BACKEND_MESSAGES.has(message)) {
      loginForm.value.password = ''
    }
  }
}
</script>

<template>
  <div
    :class="
      props.embedded
        ? 'w-full'
        : 'w-full h-full flex items-center justify-center bg-slate-50 px-4 py-8'
    "
  >
    <div
      :class="[
        'w-full max-w-[460px] mx-auto',
        props.embedded
          ? 'p-6'
          : 'p-10 border border-slate-200 shadow-[0_16px_48px_rgba(15,23,42,0.08)]',
      ]"
    >
      <div class="mb-6">
        <div class="flex justify-center mb-4">
          <IconYuxinAI type="character" :size="248" />
        </div>
        <p class="text-sm text-slate-500 mt-2 text-center">
          {{
            authView === 'login'
              ? loginModeDescription
              : authView === 'register'
                ? $t('login.registerSubtitle')
                : authView === 'registerVerify'
                  ? $t('login.registerVerifySubtitle')
                  : authView === 'challenge'
                    ? $t('login.challengeSubtitle')
                    : forgotStep === 1
                      ? $t('login.forgotEmailSubtitle')
                      : $t('login.forgotResetSubtitle')
          }}
        </p>
      </div>

      <div
        v-if="authView !== 'forgot' && errorMessage"
        class="text-sm text-red-600 bg-red-50 rounded-xl px-3 py-2 mb-4"
      >
        {{ errorMessage }}
      </div>

      <!-- 第三方登录入口暂时隐藏；后续如需恢复 OAuth-only 提示，将 SHOW_THIRD_PARTY_LOGIN 改为 true 并确认 OAuth 配置可用。 -->
      <div
        v-if="SHOW_THIRD_PARTY_LOGIN && (authView === 'login' || authView === 'register') && hasOauthOnlyProviders"
        data-testid="oauth-only-suggestions"
        class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 mb-4"
      >
        <p class="text-sm text-slate-700 mb-3">
          {{ $t('login.oauthOnlyHint') }}
        </p>
        <div class="grid grid-cols-2 gap-2">
          <a-button
            v-if="shouldRenderOauthProvider('google')"
            class="oauth-btn"
            size="large"
            type="outline"
            long
            :loading="providerLoading"
            :disabled="providerLoading"
            @click="googleLogin"
          >
            <template #icon>
              <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
                <path
                  fill="#FFC107"
                  d="M43.611 20.083H42V20H24v8h11.303A12.02 12.02 0 0 1 24 36c-6.627 0-12-5.373-12-12S17.373 12 24 12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657A19.91 19.91 0 0 0 24 4C12.955 4 4 12.955 4 24s8.955 20 20 20 20-8.955 20-20c0-1.341-.138-2.65-.389-3.917Z"
                />
                <path
                  fill="#FF3D00"
                  d="m6.306 14.691 6.571 4.819A11.968 11.968 0 0 1 24 12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657A19.91 19.91 0 0 0 24 4C16.318 4 9.653 8.337 6.306 14.691Z"
                />
                <path
                  fill="#4CAF50"
                  d="M24 44c5.166 0 9.86-1.977 13.409-5.192l-6.19-5.238A11.947 11.947 0 0 1 24 36a11.99 11.99 0 0 1-11.283-7.946l-6.522 5.025C9.505 39.556 16.227 44 24 44Z"
                />
                <path
                  fill="#1976D2"
                  d="M43.611 20.083H42V20H24v8h11.303a12.05 12.05 0 0 1-4.091 5.571l6.19 5.238C40.971 35.489 44 30.203 44 24c0-1.341-.138-2.65-.389-3.917Z"
                />
              </svg>
            </template>
            {{ $t('login.oauthLogin', { provider: OAUTH_PROVIDER_LABELS.google }) }}
          </a-button>

          <a-button
            v-if="shouldRenderOauthProvider('github')"
            class="oauth-btn"
            size="large"
            type="outline"
            long
            :loading="providerLoading"
            :disabled="providerLoading"
            @click="githubLogin"
          >
            <template #icon>
              <span
                class="inline-flex h-[18px] w-[18px] items-center justify-center rounded-full bg-[#24292f] text-white"
              >
                <icon-github :size="12" />
              </span>
            </template>
            {{ $t('login.oauthLogin', { provider: OAUTH_PROVIDER_LABELS.github }) }}
          </a-button>
        </div>
      </div>

      <div v-if="authView === 'login'">
        <a-tabs v-model:active-key="loginTab" @change="handleLoginTabChange" class="auth-tabs">
          <a-tab-pane key="password" :title="$t('login.passwordTab')" />
          <a-tab-pane v-if="showPhoneLoginTab" key="phone" :title="$t('login.phoneTab')" />
          <a-tab-pane v-if="showEmailLoginTab" key="email" :title="$t('login.emailTab')" />
        </a-tabs>

        <a-form
          v-if="loginTab === 'password'"
          :model="loginForm"
          @submit="handleSubmit"
          layout="vertical"
          size="large"
        >
          <a-form-item
            field="identifier"
            class="login-input !mb-4"
            :rules="[{ required: true, message: $t('login.identifierRequired') }]"
            :validate-trigger="['change', 'blur']"
            hide-label
          >
            <a-input v-model="loginForm.identifier" size="large" allow-clear :placeholder="$t('login.identifierPlaceholder')">
              <template #prefix>
                <icon-user class="text-slate-400" />
              </template>
            </a-input>
          </a-form-item>

          <a-form-item
            field="password"
            class="login-input !mb-2"
            :rules="[{ required: true, message: $t('login.passwordRequired') }]"
            :validate-trigger="['change', 'blur']"
            hide-label
          >
            <a-input-password v-model="loginForm.password" size="large" :placeholder="$t('login.passwordPlaceholder')">
              <template #prefix>
                <icon-lock class="text-slate-400" />
              </template>
            </a-input-password>
          </a-form-item>

          <div class="flex items-center justify-between text-sm text-slate-600 mb-4">
            <a-checkbox v-model="rememberPassword" @change="handleRememberChange">{{ $t('login.rememberPassword') }}</a-checkbox>
            <a-link class="!text-slate-500 hover:!text-slate-700" @click="openForgotPassword">
              {{ $t('login.forgotPassword') }}
            </a-link>
          </div>

          <a-button
            :loading="passwordLoginLoading || directRegisterLoading"
            size="large"
            type="primary"
            html-type="submit"
            long
            class="login-submit-btn !text-base !font-medium"
          >
            {{ $t('login.signIn') }}
          </a-button>
        </a-form>

        <a-form
          v-else-if="loginTab === 'phone'"
          :model="phoneLoginForm"
          @submit.prevent="handlePhoneCodeLogin"
          layout="vertical"
          size="large"
        >
          <a-form-item field="phone" class="login-input !mb-4" hide-label>
            <a-input
              v-model="phoneLoginForm.phone"
              size="large"
              allow-clear
              :placeholder="$t('login.phonePlaceholder')"
            >
              <template #prefix>
                <icon-phone class="text-slate-400" />
              </template>
            </a-input>
          </a-form-item>

          <a-form-item field="code" class="login-input !mb-2" hide-label>
            <a-input
              v-model="phoneLoginForm.code"
              size="large"
              maxlength="6"
              :placeholder="$t('login.codePlaceholder')"
              @keyup.enter="handlePhoneCodeLogin"
            >
              <template #prefix>
                <icon-safe class="text-slate-400" />
              </template>
              <template #suffix>
                <a-button
                  type="text"
                  size="mini"
                  class="!text-slate-500"
                  :loading="sendingPhoneLoginCode"
                  :disabled="phoneLoginCountdown > 0"
                  @click="handleSendPhoneLoginCode"
                >
                  {{ phoneLoginCountdownText }}
                </a-button>
              </template>
            </a-input>
          </a-form-item>

          <a-button
            :loading="phoneCodeLoginLoading"
            size="large"
            type="primary"
            long
            class="login-submit-btn !text-base !font-medium"
            @click="handlePhoneCodeLogin"
          >
            {{ $t('login.phoneLogin') }}
          </a-button>
        </a-form>

        <a-form
          v-else-if="loginTab === 'email'"
          :model="emailLoginForm"
          @submit.prevent="handleEmailCodeLogin"
          layout="vertical"
          size="large"
        >
          <a-form-item field="email" class="login-input !mb-4" hide-label>
            <a-input
              v-model="emailLoginForm.email"
              size="large"
              allow-clear
              :placeholder="$t('login.emailLoginPlaceholder')"
            >
              <template #prefix>
                <icon-email class="text-slate-400" />
              </template>
            </a-input>
          </a-form-item>
          <a-form-item field="code" class="login-input !mb-2" hide-label>
            <a-input
              v-model="emailLoginForm.code"
              size="large"
              maxlength="6"
              :placeholder="$t('login.codePlaceholder')"
              @keyup.enter="handleEmailCodeLogin"
            >
              <template #prefix>
                <icon-safe class="text-slate-400" />
              </template>
              <template #suffix>
                <a-button
                  type="text"
                  size="mini"
                  class="!text-slate-500"
                  :loading="sendingEmailLoginCode"
                  :disabled="emailLoginCountdown > 0"
                  @click="handleSendEmailLoginCode"
                >
                  {{ emailLoginCountdownText }}
                </a-button>
              </template>
            </a-input>
          </a-form-item>

          <a-button
            :loading="emailCodeLoginLoading"
            size="large"
            type="primary"
            long
            class="login-submit-btn !text-base !font-medium"
            @click="handleEmailCodeLogin"
          >
            {{ $t('login.emailLogin') }}
          </a-button>
        </a-form>

        <div class="text-center mt-4">
          <span class="text-sm text-slate-500">{{ $t('login.noAccount') }}</span>
          <a-link class="!text-slate-600 hover:!text-slate-800" @click="openRegister">
            {{ $t('login.registerEntry') }}
          </a-link>
        </div>

        <!-- 第三方登录按钮暂时隐藏；后续重新启用 Google/GitHub 登录时，将 SHOW_THIRD_PARTY_LOGIN 改为 true 并确认 OAuth 配置可用。 -->
        <div v-if="SHOW_THIRD_PARTY_LOGIN" class="grid grid-cols-2 gap-2 mt-5">
          <a-button
            class="oauth-btn"
            size="large"
            type="outline"
            long
            :loading="providerLoading"
            :disabled="providerLoading"
            @click="googleLogin"
          >
            <template #icon>
              <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
                <path
                  fill="#FFC107"
                  d="M43.611 20.083H42V20H24v8h11.303A12.02 12.02 0 0 1 24 36c-6.627 0-12-5.373-12-12S17.373 12 24 12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657A19.91 19.91 0 0 0 24 4C12.955 4 4 12.955 4 24s8.955 20 20 20 20-8.955 20-20c0-1.341-.138-2.65-.389-3.917Z"
                />
                <path
                  fill="#FF3D00"
                  d="m6.306 14.691 6.571 4.819A11.968 11.968 0 0 1 24 12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657A19.91 19.91 0 0 0 24 4C16.318 4 9.653 8.337 6.306 14.691Z"
                />
                <path
                  fill="#4CAF50"
                  d="M24 44c5.166 0 9.86-1.977 13.409-5.192l-6.19-5.238A11.947 11.947 0 0 1 24 36a11.99 11.99 0 0 1-11.283-7.946l-6.522 5.025C9.505 39.556 16.227 44 24 44Z"
                />
                <path
                  fill="#1976D2"
                  d="M43.611 20.083H42V20H24v8h11.303a12.05 12.05 0 0 1-4.091 5.571l6.19 5.238C40.971 35.489 44 30.203 44 24c0-1.341-.138-2.65-.389-3.917Z"
                />
              </svg>
            </template>
            Google
          </a-button>

          <a-button
            class="oauth-btn"
            size="large"
            type="outline"
            long
            :loading="providerLoading"
            :disabled="providerLoading"
            @click="githubLogin"
          >
            <template #icon>
              <span
                class="inline-flex h-[18px] w-[18px] items-center justify-center rounded-full bg-[#24292f] text-white"
              >
                <icon-github :size="12" />
              </span>
            </template>
            GitHub
          </a-button>
        </div>
      </div>

      <div v-else-if="authView === 'register'">
        <div class="rounded-xl bg-sky-50 border border-sky-100 px-4 py-3 text-sm text-sky-900 mb-4">
          {{ registerEntryDescription }}
        </div>

        <a-tabs v-model:active-key="registerTab" @change="handleRegisterTabChange" class="auth-tabs">
          <a-tab-pane key="direct" :title="$t('login.directRegisterTab')" />
          <a-tab-pane v-if="showEmailRegisterTab" key="email" :title="$t('login.emailRegisterTab')" />
          <a-tab-pane v-if="showPhoneRegisterTab" key="phone" :title="$t('login.phoneRegisterTab')" />
        </a-tabs>

        <div v-if="registerTab === 'direct'">
          <a-form-item hide-label class="login-input !mb-4">
            <a-input
              v-model="registerForm.username"
              size="large"
              allow-clear
              :placeholder="$t('login.usernamePlaceholder')"
              @keyup.enter="handleStartRegister"
            >
              <template #prefix>
                <icon-user class="text-slate-400" />
              </template>
            </a-input>
          </a-form-item>

          <a-form-item hide-label class="login-input !mb-4">
            <a-input-password
              v-model="registerForm.password"
              size="large"
              :placeholder="$t('login.registerPasswordPlaceholder')"
              @keyup.enter="handleStartRegister"
            >
              <template #prefix>
                <icon-lock class="text-slate-400" />
              </template>
            </a-input-password>
          </a-form-item>

          <a-form-item hide-label class="login-input !mb-4">
            <a-input
              v-model="registerForm.invite_code"
              size="large"
              :disabled="inviteCodeLocked"
              :placeholder="$t('login.inviteCodePlaceholder')"
              @keyup.enter="handleStartRegister"
            />
            <div v-if="inviteCodeLocked" class="mt-1 text-xs text-sky-600">
              <span v-if="registerInviteInfoLoading">{{ $t('common.loading') }}</span>
              <template v-else>
                <span>{{ $t('login.inviteCodeLockedHint') }}</span>
                <span v-if="inviteInfo?.inviter_name"> · {{ $t('login.inviterName', { name: inviteInfo.inviter_name }) }}</span>
              </template>
            </div>
          </a-form-item>

          <a-button
            :loading="directRegisterLoading"
            size="large"
            type="primary"
            long
            class="login-submit-btn !text-base !font-medium"
            @click="handleStartRegister"
          >
            注册
          </a-button>
        </div>

        <div v-else-if="registerTab === 'email'">
          <div class="rounded-xl bg-sky-50 border border-sky-100 px-4 py-3 text-sm text-sky-900 mb-4">
            {{ registerVerifyDescription }}
          </div>

          <a-form-item hide-label class="login-input !mb-4">
            <a-input
              v-model="registerForm.email"
              size="large"
              allow-clear
              :placeholder="$t('login.emailPlaceholder')"
              @keyup.enter="handleStartEmailRegister"
            >
              <template #prefix>
                <icon-email class="text-slate-400" />
              </template>
            </a-input>
          </a-form-item>

          <a-form-item hide-label class="login-input !mb-4">
            <a-input-password
              v-model="registerForm.password"
              size="large"
              :placeholder="$t('login.registerPasswordPlaceholder')"
            >
              <template #prefix>
                <icon-lock class="text-slate-400" />
              </template>
            </a-input-password>
          </a-form-item>

          <a-form-item hide-label class="login-input !mb-4">
            <a-input
              v-model="registerForm.invite_code"
              size="large"
              :disabled="inviteCodeLocked"
              :placeholder="$t('login.inviteCodePlaceholder')"
            />
          </a-form-item>

          <a-form-item hide-label class="login-input !mb-3">
            <a-input
              v-model="registerForm.verify_code"
              size="large"
              maxlength="6"
              :placeholder="$t('login.codePlaceholder')"
              @keyup.enter="handleVerifyEmailRegister"
            >
              <template #prefix>
                <icon-safe class="text-slate-400" />
              </template>
              <template #suffix>
                <a-button
                  type="text"
                  size="mini"
                  class="!text-slate-500"
                  :loading="sendingRegisterCode"
                  :disabled="registerCountdown > 0"
                  @click="handleStartEmailRegister"
                >
                  {{ registerCountdownText }}
                </a-button>
              </template>
            </a-input>
          </a-form-item>

          <a-button
            :loading="verifyRegisterLoading"
            size="large"
            type="primary"
            long
            class="login-submit-btn !text-base !font-medium"
            @click="handleVerifyEmailRegister"
          >
            {{ $t('login.verifyAndRegister') }}
          </a-button>
        </div>

        <div v-else-if="registerTab === 'phone'">
          <a-form-item hide-label class="login-input !mb-4">
            <a-input
              v-model="phoneRegisterForm.phone"
              size="large"
              allow-clear
              :placeholder="$t('login.phonePlaceholder')"
            >
              <template #prefix>
                <icon-phone class="text-slate-400" />
              </template>
            </a-input>
          </a-form-item>

          <a-form-item hide-label class="login-input !mb-4">
            <a-input
              v-model="phoneRegisterForm.username"
              size="large"
              allow-clear
              :placeholder="$t('login.phoneRegisterUsernamePlaceholder')"
            >
              <template #prefix>
                <icon-user class="text-slate-400" />
              </template>
            </a-input>
          </a-form-item>

          <a-form-item hide-label class="login-input !mb-4">
            <a-input-password
              v-model="phoneRegisterForm.password"
              size="large"
              :placeholder="$t('login.phoneRegisterPasswordPlaceholder')"
            >
              <template #prefix>
                <icon-lock class="text-slate-400" />
              </template>
            </a-input-password>
          </a-form-item>

          <a-form-item hide-label class="login-input !mb-3">
            <a-input
              v-model="phoneRegisterForm.code"
              size="large"
              maxlength="6"
              :placeholder="$t('login.codePlaceholder')"
              @keyup.enter="handlePhoneRegisterVerify"
            >
              <template #prefix>
                <icon-safe class="text-slate-400" />
              </template>
              <template #suffix>
                <a-button
                  type="text"
                  size="mini"
                  class="!text-slate-500"
                  :loading="sendingPhoneRegisterCode"
                  :disabled="phoneRegisterCountdown > 0"
                  @click="handleSendPhoneRegisterCode"
                >
                  {{ phoneRegisterCountdownText }}
                </a-button>
              </template>
            </a-input>
          </a-form-item>

          <a-button
            :loading="phoneRegisterVerifyLoading"
            size="large"
            type="primary"
            long
            class="login-submit-btn !text-base !font-medium"
            @click="handlePhoneRegisterVerify"
          >
            {{ $t('login.phoneRegister') }}
          </a-button>
        </div>

        <div class="text-center mt-4">
          <span class="text-sm text-slate-500">{{ $t('login.haveAccount') }}</span>
          <a-link class="!text-slate-600 hover:!text-slate-800" @click="backToLogin">
            {{ $t('login.backToLogin') }}
          </a-link>
        </div>
      </div>

      <div v-else-if="authView === 'challenge'">
        <div class="rounded-xl bg-amber-50 border border-amber-100 px-4 py-3 text-sm text-amber-900 mb-4">
          {{ challengeDescription }}
        </div>

        <div
          v-if="loginChallenge.channels.length > 1"
          class="grid grid-cols-2 gap-3 mb-4"
          data-testid="challenge-channel-select"
        >
          <button
            v-for="channel in loginChallenge.channels"
            :key="channel.type"
            type="button"
            class="challenge-channel-card"
            :class="{ 'challenge-channel-card--active': loginChallenge.selected_channel === channel.type }"
            @click="handleSelectChallengeChannel(channel.type)"
          >
            <span class="text-sm font-medium text-slate-800">
              {{ channel.type === 'phone' ? $t('login.phoneChannel') : $t('login.emailChannel') }}
            </span>
            <span class="text-xs text-slate-500">{{ channel.masked || '—' }}</span>
          </button>
        </div>

        <div v-if="loginChallenge.channels.length > 0">
          <div v-if="challengeVerificationHint" class="text-sm text-slate-500 mb-3">
            {{ challengeVerificationHint }}
          </div>

          <a-form-item hide-label class="login-input !mb-4">
            <a-input
              v-model="challengeCode"
              size="large"
              :placeholder="$t('login.codePlaceholder')"
              maxlength="6"
              :disabled="loginChallenge.channels.length > 1 && !loginChallenge.selected_channel"
              @keyup.enter="handleVerifyChallenge"
            >
              <template #prefix>
                <icon-safe class="text-slate-400" />
              </template>
              <template #suffix>
                <a-button
                  type="text"
                  size="mini"
                  class="!text-slate-500"
                  :loading="sendingChallengeCode"
                  :disabled="
                    challengeCountdown > 0 ||
                    (loginChallenge.channels.length > 1 && !loginChallenge.selected_channel)
                  "
                  @click="handleRequestChallengeCode"
                >
                  {{ challengeGetCodeText }}
                </a-button>
              </template>
            </a-input>
          </a-form-item>

          <a-button
            :loading="verifyLoginChallengeLoading"
            size="large"
            type="primary"
            long
            class="login-submit-btn !text-base !font-medium"
            @click="handleVerifyChallenge"
          >
            {{ $t('login.verifyAndLogin') }}
          </a-button>
        </div>

        <div class="text-center mt-4">
          <a-link class="!text-slate-500 hover:!text-slate-700" @click="backToLogin">
            <icon-left />
            {{ $t('login.backToLogin') }}
          </a-link>
        </div>
      </div>

      <div v-else>
        <div v-if="forgotStep === 1">
          <a-form-item hide-label class="login-input !mb-4">
            <a-input
              v-model="forgotForm.email"
              size="large"
              allow-clear
              :placeholder="$t('login.forgotEmailPlaceholder')"
              @keyup.enter="handleSendCode"
            >
              <template #prefix>
                <icon-email class="text-slate-400" />
              </template>
            </a-input>
          </a-form-item>
          <a-button
            :loading="sendingCode"
            size="large"
            type="primary"
            long
            class="login-submit-btn !text-base !font-medium"
            @click="handleSendCode"
          >
            {{ $t('common.actions.sendCode') }}
          </a-button>
        </div>

        <div v-else>
          <a-form-item hide-label class="login-input !mb-3">
            <a-input
              v-model="forgotForm.code"
              size="large"
              :placeholder="$t('login.codePlaceholder')"
              maxlength="6"
              @keyup.enter="handleResetPassword"
            >
              <template #prefix>
                <icon-safe class="text-slate-400" />
              </template>
              <template #suffix>
                <a-button
                  type="text"
                  size="mini"
                  class="!text-slate-500"
                  :disabled="countdown > 0"
                  @click="handleResendCode"
                >
                  {{ countdownText }}
                </a-button>
              </template>
            </a-input>
          </a-form-item>

          <a-form-item hide-label class="login-input !mb-3">
            <a-input-password
              v-model="forgotForm.new_password"
              size="large"
              :placeholder="$t('login.newPasswordPlaceholder')"
            >
              <template #prefix>
                <icon-lock class="text-slate-400" />
              </template>
            </a-input-password>
          </a-form-item>

          <a-form-item hide-label class="login-input !mb-3">
            <a-input-password
              v-model="forgotForm.confirm_password"
              size="large"
              :placeholder="$t('login.confirmPasswordPlaceholder')"
              @keyup.enter="handleResetPassword"
            >
              <template #prefix>
                <icon-lock class="text-slate-400" />
              </template>
            </a-input-password>
          </a-form-item>

          <a-button
            :loading="resetting"
            size="large"
            type="primary"
            long
            class="login-submit-btn !text-base !font-medium"
            @click="handleResetPassword"
          >
            {{ $t('login.resetPassword') }}
          </a-button>
        </div>

        <div class="text-center mt-4">
          <a-link class="!text-slate-500 hover:!text-slate-700" @click="handleForgotBack">
            <icon-left />
            {{ forgotStep === 1 ? $t('login.backToLogin') : $t('login.backToPrevious') }}
          </a-link>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-input :deep(.arco-input-wrapper) {
  border-radius: 10px;
  background: #f8fafc;
  border-color: #e2e8f0;
}

.login-input :deep(.arco-input-wrapper:hover) {
  border-color: #cbd5e1;
  background: #fff;
}

.login-input :deep(.arco-input-wrapper.arco-input-focus) {
  border-color: #3b82f6;
  background: #fff;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.12);
}

.login-submit-btn {
  border-radius: 10px;
  height: 42px;
}

.oauth-btn {
  border-radius: 10px;
  height: 42px;
  border-color: #e2e8f0;
  color: #334155;
  background: #fff;
}

.oauth-btn:hover {
  border-color: #cbd5e1;
  background: #f8fafc;
}

.auth-tabs {
  margin-bottom: 16px;
}

.auth-tabs :deep(.arco-tabs-header-title) {
  font-size: 14px;
  color: #64748b;
}

.challenge-channel-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.challenge-channel-card:hover {
  border-color: #cbd5e1;
  background: #f8fafc;
}

.challenge-channel-card--active {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.12);
}
</style>
