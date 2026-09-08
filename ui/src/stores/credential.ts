import { ref } from 'vue'
import { defineStore } from 'pinia'
import storage from '@/utils/storage'
import { syncCredentialToDesktop } from '@/utils/desktop-credential-sync'

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
    syncCredentialToDesktop(credential.value)
  }

  const clear = () => {
    credential.value = initCredential
    storage.remove('credential')
    void syncCredentialToDesktop(null)
  }

  return { credential, update, clear }
})
