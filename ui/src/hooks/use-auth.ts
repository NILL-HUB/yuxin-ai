import { ref } from 'vue'
import {
  directRegister,
  getRegisterInviteInfo,
  logout,
  passwordLogin,
  prepareRegister,
  resendLoginChallenge,
  verifyLoginChallenge,
  verifyRegister,
} from '@/services/auth'
import { Message } from '@arco-design/web-vue'
import { type LoginAuthorizationData, type RegisterInviteInfo } from '@/models/auth'

export const useLogout = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)

  // 2.定义退出登录处理器
  const handleLogout = async () => {
    try {
      loading.value = true
      const resp = await logout()
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleLogout }
}

export const usePasswordLogin = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const authorization = ref<LoginAuthorizationData>({})

  // 2.定义账号密码处理器
  const handlePasswordLogin = async (identifier: string, password: string) => {
    try {
      loading.value = true
      const resp = await passwordLogin(identifier, password)
      authorization.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, authorization, handlePasswordLogin }
}

export const usePrepareRegister = () => {
  const loading = ref(false)

  const handlePrepareRegister = async (username: string, email: string, password: string, inviteCode?: string) => {
    try {
      loading.value = true
      const code = (inviteCode || '').trim()
      const resp = code
        ? await prepareRegister(username, email, password, code)
        : await prepareRegister(username, email, password)
      return resp
    } finally {
      loading.value = false
    }
  }

  return { loading, handlePrepareRegister }
}

export const useDirectRegister = () => {
  const loading = ref(false)
  const authorization = ref<LoginAuthorizationData>({})

  const handleDirectRegister = async (username: string, password: string, inviteCode?: string) => {
    try {
      loading.value = true
      const code = (inviteCode || '').trim()
      const resp = code
        ? await directRegister(username, password, code)
        : await directRegister(username, password)
      authorization.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, authorization, handleDirectRegister }
}

export const useVerifyRegister = () => {
  const loading = ref(false)
  const authorization = ref<LoginAuthorizationData>({})

  const handleVerifyRegister = async (
    username: string,
    email: string,
    password: string,
    code: string,
    inviteCode?: string,
  ) => {
    try {
      loading.value = true
      const invite = (inviteCode || '').trim()
      const resp = invite
        ? await verifyRegister(username, email, password, code, invite)
        : await verifyRegister(username, email, password, code)
      authorization.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, authorization, handleVerifyRegister }
}

export const useRegisterInviteInfo = () => {
  const loading = ref(false)
  const info = ref<RegisterInviteInfo | null>(null)

  const handleQueryInviteInfo = async (code: string) => {
    try {
      loading.value = true
      const resp = await getRegisterInviteInfo(code)
      info.value = resp.data
      return resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, info, handleQueryInviteInfo }
}

export const useVerifyLoginChallenge = () => {
  const loading = ref(false)
  const authorization = ref<LoginAuthorizationData>({})

  const handleVerifyLoginChallenge = async (challenge_id: string, code: string, channel = '') => {
    try {
      loading.value = true
      const resp = await verifyLoginChallenge(challenge_id, code, channel)
      authorization.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, authorization, handleVerifyLoginChallenge }
}

export const useResendLoginChallenge = () => {
  const loading = ref(false)

  const handleResendLoginChallenge = async (challenge_id: string, channel = '') => {
    try {
      loading.value = true
      const resp = await resendLoginChallenge(challenge_id, channel)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleResendLoginChallenge }
}
