import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAdminStore } from '@/stores/admin'
import storage from '@/utils/storage'

describe('useAdminStore', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('updates and persists admin profile with roles and permissions', () => {
    const store = useAdminStore()

    store.update({
      id: 'admin-1',
      username: 'admin',
      email: '',
      name: 'Root',
      avatar: '',
      status: 'active',
      roles: ['super_admin'],
      permissions: ['admin:access', 'app:read', 'app:update'],
    })

    expect(store.admin.username).toBe('admin')
    expect(store.admin.roles).toEqual(['super_admin'])
    expect(store.admin.permissions).toEqual(['admin:access', 'app:read', 'app:update'])
    expect(storage.get('admin')).toEqual(store.admin)
  })

  it('checks single any and all permissions', () => {
    const store = useAdminStore()
    store.update({
      id: 'admin-1',
      username: 'admin',
      email: '',
      name: 'Root',
      avatar: '',
      status: 'active',
      roles: ['operator'],
      permissions: ['app:read', 'workflow:read'],
    })

    expect(store.hasPermission('app:read')).toBe(true)
    expect(store.hasPermission('app:update')).toBe(false)
    expect(store.hasAnyPermission(['app:update', 'workflow:read'])).toBe(true)
    expect(store.hasAnyPermission(['app:update', 'workflow:update'])).toBe(false)
    expect(store.hasAllPermissions(['app:read', 'workflow:read'])).toBe(true)
    expect(store.hasAllPermissions(['app:read', 'workflow:update'])).toBe(false)
  })

  it('clears admin state and persisted value', () => {
    const store = useAdminStore()
    store.update({
      id: 'admin-1',
      username: 'admin',
      email: '',
      name: 'Root',
      avatar: '',
      status: 'active',
      roles: ['super_admin'],
      permissions: ['admin:access'],
    })

    store.clear()

    expect(store.admin).toEqual({
      id: '',
      username: '',
      email: '',
      name: '',
      avatar: '',
      status: '',
      roles: [],
      permissions: [],
    })
    expect(storage.get('admin')).toBe('')
  })
})
