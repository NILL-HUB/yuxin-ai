import { ref } from 'vue'
import { defineStore } from 'pinia'
import storage from '@/utils/storage'

// 定义基础授权凭证信息
const initCredential = {
  access_token: '',
  expire_at: 0,
}

type Credential = typeof initCredential

export const useCredentialStore = defineStore('credential', () => {
  const credential = ref<Credential>(storage.get('credential', initCredential) as Credential)

  const update = (params: Partial<Credential>) => {
    credential.value = { ...initCredential, ...params }
    storage.set('credential', credential.value)
  }

  const clear = () => {
    credential.value = initCredential
    storage.remove('credential')
  }

  return { credential, update, clear }
})
