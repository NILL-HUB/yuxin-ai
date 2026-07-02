import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { adminChangePassword, adminLogin, adminLogout, getCurrentAdmin } from '@/services/admin-auth'
import { useAdminStore } from '@/stores/admin'
import { useCredentialStore } from '@/stores/credential'
import storage from '@/utils/storage'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
}))

describe('admin auth service', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('posts admin login credentials and writes admin credential only', async () => {
    vi.mocked(request.post).mockResolvedValue({
      data: {
        access_token: 'admin-token',
        admin_access_token: 'admin-token',
        user_access_token: 'user-token',
        expire_at: 1893456000,
        user_expire_at: 1896048000,
        user: {
          id: 'account-1',
          username: 'admin',
          email: '',
          name: 'Root',
          avatar: '',
          status: 'active',
        },
        admin_user: {
          id: 'admin-1',
          username: 'admin',
          email: '',
          name: 'Root',
          avatar: '',
          status: 'active',
          roles: ['super_admin'],
          permissions: ['admin:access'],
        },
      },
      message: 'ok',
    } as never)

    const credentialStore = useCredentialStore()
    expect(credentialStore.credential.access_token).toBe('')

    const result = await adminLogin('admin', 'Root123456')
    const adminStore = useAdminStore()

    expect(request.post).toHaveBeenCalledWith('/admin/auth/login', {
      body: { identifier: 'admin', password: 'Root123456' },
    })
    expect(result.data.access_token).toBe('admin-token')
    expect(storage.get('admin_credential')).toEqual({ access_token: 'admin-token', expire_at: 1893456000 })
    expect(storage.get('credential')).toBe('')
    expect(credentialStore.credential.access_token).toBe('')
    expect(adminStore.admin.username).toBe('admin')
    expect(adminStore.admin.permissions).toEqual(['admin:access'])
  })

  it('loads current admin and updates admin store', async () => {
    vi.mocked(request.get).mockResolvedValue({
      data: {
        id: 'admin-1',
        username: 'admin',
        email: '',
        name: 'Root',
        avatar: '',
        status: 'active',
        roles: ['super_admin'],
        permissions: ['admin:access'],
      },
      message: 'ok',
    } as never)

    const result = await getCurrentAdmin()
    const adminStore = useAdminStore()

    expect(request.get).toHaveBeenCalledWith('/admin/auth/me')
    expect(result.data.username).toBe('admin')
    expect(adminStore.admin.roles).toEqual(['super_admin'])
  })

  it('posts admin password change request', async () => {
    vi.mocked(request.post).mockResolvedValue({
      data: {
        id: 'admin-1',
        username: 'admin',
        email: '',
        name: 'Root',
        avatar: '',
        status: 'active',
        roles: ['super_admin'],
        permissions: ['admin:access'],
      },
      message: 'ok',
    } as never)

    await adminChangePassword('Root123456', 'New_123456')

    expect(request.post).toHaveBeenCalledWith('/admin/auth/password', {
      body: { current_password: 'Root123456', new_password: 'New_123456' },
    })
  })

  it('posts admin logout and clears admin state only', async () => {
    storage.set('credential', { access_token: 'user-token', expire_at: 1896048000 })
    storage.set('admin_credential', { access_token: 'admin-token', expire_at: 1893456000 })
    const adminStore = useAdminStore()
    adminStore.update({
      id: 'admin-1',
      username: 'admin',
      email: '',
      name: 'Root',
      avatar: '',
      status: 'active',
      roles: ['super_admin'],
      permissions: ['admin:access'],
    })
    vi.mocked(request.post).mockResolvedValue({ data: {}, message: '退出登录成功' } as never)

    await adminLogout()

    expect(request.post).toHaveBeenCalledWith('/admin/auth/logout')
    expect(storage.get('admin_credential')).toBe('')
    expect(storage.get('credential')).toEqual({ access_token: 'user-token', expire_at: 1896048000 })
    expect(adminStore.admin.email).toBe('')
  })
})
