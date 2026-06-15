import { ref } from 'vue'
import { defineStore } from 'pinia'
import storage from '@/utils/storage'

export interface AdminProfile {
  id: string
  username: string
  email: string
  name: string
  avatar: string
  status: string
  roles: string[]
  permissions: string[]
}

const initAdmin: AdminProfile = {
  id: '',
  username: '',
  email: '',
  name: '',
  avatar: '',
  status: '',
  roles: [],
  permissions: [],
}

export const useAdminStore = defineStore('admin', () => {
  const admin = ref<AdminProfile>(storage.get('admin', initAdmin))

  const update = (params: AdminProfile) => {
    admin.value = params
    storage.set('admin', params)
  }

  const clear = () => {
    admin.value = initAdmin
    storage.remove('admin')
  }

  const hasPermission = (permission: string) => {
    return admin.value.permissions.includes(permission)
  }

  const hasAnyPermission = (permissions: string[]) => {
    return permissions.some((permission) => hasPermission(permission))
  }

  const hasAllPermissions = (permissions: string[]) => {
    return permissions.every((permission) => hasPermission(permission))
  }

  return { admin, update, clear, hasPermission, hasAnyPermission, hasAllPermissions }
})
