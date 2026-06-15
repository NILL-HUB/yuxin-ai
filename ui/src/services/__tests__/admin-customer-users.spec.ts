import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  disableCustomerUser,
  enableCustomerUser,
  getCustomerUser,
  listCustomerUsers,
  revokeCustomerUserSessions,
} from '@/services/admin-customer-users'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
}))

describe('admin customer users service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists customer users with filters and pagination', async () => {
    vi.mocked(request.get).mockResolvedValue({ data: { list: [], paginator: { total_record: 0 } } } as never)

    await listCustomerUsers({ keyword: 'user', status: 'active', current_page: 1, page_size: 20 })

    expect(request.get).toHaveBeenCalledWith('/admin/users', {
      params: { keyword: 'user', status: 'active', current_page: 1, page_size: 20 },
    })
  })

  it('gets customer user detail', async () => {
    vi.mocked(request.get).mockResolvedValue({ data: { id: 'user-1', sessions: [] } } as never)

    await getCustomerUser('user-1')

    expect(request.get).toHaveBeenCalledWith('/admin/users/user-1')
  })

  it('disables customer user with reason', async () => {
    vi.mocked(request.post).mockResolvedValue({ data: { id: 'user-1', status: 'disabled' } } as never)

    await disableCustomerUser('user-1', 'risk')

    expect(request.post).toHaveBeenCalledWith('/admin/users/user-1/disable', { body: { reason: 'risk' } })
  })

  it('enables customer user', async () => {
    vi.mocked(request.post).mockResolvedValue({ data: { id: 'user-1', status: 'active' } } as never)

    await enableCustomerUser('user-1')

    expect(request.post).toHaveBeenCalledWith('/admin/users/user-1/enable')
  })

  it('revokes customer user sessions', async () => {
    vi.mocked(request.post).mockResolvedValue({ data: { revoked_sessions: 2 } } as never)

    await revokeCustomerUserSessions('user-1')

    expect(request.post).toHaveBeenCalledWith('/admin/users/user-1/sessions/revoke')
  })
})
