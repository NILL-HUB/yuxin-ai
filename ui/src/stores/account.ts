import { ref } from 'vue'
import { defineStore } from 'pinia'
import storage from '@/utils/storage'

// 定义账号初始化数据
const initAccount = {
  id: '',
  name: '',
  email: '',
  avatar: '',
  last_login_ip: '',
  last_login_location: '',
  last_login_at: 0,
  created_at: 0,
  password_set: false,
  oauth_bindings: [] as Array<{ provider: string; bound: boolean; bound_at: number }>,
}

type Account = typeof initAccount

export const useAccountStore = defineStore('account', () => {
  const account = ref<Account>(storage.get('account', initAccount) as Account)

  const update = (params: Partial<Account>) => {
    account.value = { ...initAccount, ...params }
    storage.set('account', account.value)
  }

  const clear = () => {
    account.value = initAccount
    storage.remove('account')
  }

  return { account, update, clear }
})
