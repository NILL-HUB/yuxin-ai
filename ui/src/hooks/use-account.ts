import { ref } from 'vue'
import {
  getAccountLoginHistory,
  getAccountSessions,
  getCurrentUser,
  revokeAccountSession,
  revokeOtherAccountSessions,
  sendChangeEmailCode,
  updateAvatar,
  updateEmail,
  updateName,
  updatePassword,
  unbindOAuth,
} from '@/services/account'
import {
  bindPhone,
  sendBindPhoneCode,
  sendVerifyEmailCode,
  unbindPhone,
  verifyEmail,
} from '@/services/account-security'
import { Message } from '@arco-design/web-vue'
import type {
  GetAccountSessionsResponse,
  GetCurrentUserResponse,
} from '@/models/account'
export const useGetCurrentUser = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const current_user = ref<GetCurrentUserResponse['data']>({} as GetCurrentUserResponse['data'])

  // 2.定义加载数据处理器
  const loadCurrentUser = async () => {
    try {
      loading.value = true
      const resp = await getCurrentUser()
      current_user.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, current_user, loadCurrentUser }
}

export const useUpdateAvatar = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)

  // 2.定义更新头像处理器
  const handleUpdateAvatar = async (avatar: string) => {
    try {
      loading.value = true
      const resp = await updateAvatar(avatar)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleUpdateAvatar }
}

export const useSendChangeEmailCode = () => {
  const loading = ref(false)

  const handleSendChangeEmailCode = async (email: string) => {
    try {
      loading.value = true
      const resp = await sendChangeEmailCode(email)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleSendChangeEmailCode }
}

export const useUpdateName = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)

  // 2.定义更新名字处理器
  const handleUpdateName = async (name: string) => {
    try {
      loading.value = true
      await updateName(name)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleUpdateName }
}

export const useUpdateEmail = () => {
  const loading = ref(false)

  const handleUpdateEmail = async (email: string, code: string, current_password: string = '') => {
    try {
      loading.value = true
      const resp = await updateEmail(email, code, current_password)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleUpdateEmail }
}

export const useUpdatePassword = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)

  // 2.定义更新密码处理器
  const handleUpdatePassword = async (current_password: string, new_password: string) => {
    try {
      loading.value = true
      const resp = await updatePassword(current_password, new_password)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleUpdatePassword }
}

export const useGetAccountSessions = () => {
  const loading = ref(false)
  const session_state = ref<GetAccountSessionsResponse['data']>({
    session_capable: false,
    current_session_id: null,
    sessions: [],
  })

  const loadAccountSessions = async () => {
    try {
      loading.value = true
      const resp = await getAccountSessions()
      session_state.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, session_state, loadAccountSessions }
}

export const useGetAccountLoginHistory = () => {
  const loading = ref(false)
  const history_state = ref<{
    history: Array<Record<string, unknown>>
    total: number
    current_page: number
    page_size: number
  }>({
    history: [],
    total: 0,
    current_page: 1,
    page_size: 5,
  })

  const loadAccountLoginHistory = async (params?: {
    status?: string
    search?: string
    current_page?: number
    page_size?: number
  }) => {
    try {
      loading.value = true
      const resp = await getAccountLoginHistory(params)
      history_state.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, history_state, loadAccountLoginHistory }
}

export const useRevokeAccountSession = () => {
  const loading = ref(false)

  const handleRevokeAccountSession = async (session_id: string) => {
    try {
      loading.value = true
      const resp = await revokeAccountSession(session_id)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleRevokeAccountSession }
}

export const useRevokeOtherAccountSessions = () => {
  const loading = ref(false)

  const handleRevokeOtherAccountSessions = async () => {
    try {
      loading.value = true
      const resp = await revokeOtherAccountSessions()
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleRevokeOtherAccountSessions }
}

export const useUnbindOAuth = () => {
  const loading = ref(false)

  const handleUnbindOAuth = async (provider_name: string) => {
    try {
      loading.value = true
      const resp = await unbindOAuth(provider_name)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleUnbindOAuth }
}

export const useSendBindPhoneCode = () => {
  const loading = ref(false)

  const handleSendBindPhoneCode = async (phone: string) => {
    try {
      loading.value = true
      const resp = await sendBindPhoneCode(phone)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleSendBindPhoneCode }
}

export const useBindPhone = () => {
  const loading = ref(false)

  const handleBindPhone = async (phone: string, code: string) => {
    try {
      loading.value = true
      const resp = await bindPhone(phone, code)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleBindPhone }
}

export const useUnbindPhone = () => {
  const loading = ref(false)

  const handleUnbindPhone = async (code: string) => {
    try {
      loading.value = true
      const resp = await unbindPhone(code)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleUnbindPhone }
}

export const useSendVerifyEmailCode = () => {
  const loading = ref(false)

  const handleSendVerifyEmailCode = async () => {
    try {
      loading.value = true
      const resp = await sendVerifyEmailCode()
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleSendVerifyEmailCode }
}

export const useVerifyEmail = () => {
  const loading = ref(false)

  const handleVerifyEmail = async (code: string) => {
    try {
      loading.value = true
      const resp = await verifyEmail(code)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleVerifyEmail }
}
