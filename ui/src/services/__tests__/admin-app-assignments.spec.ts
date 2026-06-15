import { beforeEach, describe, expect, it, vi } from 'vitest'
import { assignAppsToUser, listUserAppAssignments, revokeUserAppAssignment } from '@/services/admin-app-assignments'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
}))

describe('admin app assignments service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists assignments for a customer user', async () => {
    vi.mocked(request.get).mockResolvedValue({ list: [] } as never)

    await listUserAppAssignments('user-1')

    expect(request.get).toHaveBeenCalledWith('/admin/users/user-1/app-assignments')
  })

  it('assigns apps to a customer user', async () => {
    vi.mocked(request.post).mockResolvedValue({ assigned: 1, reactivated: 0, skipped: 0, list: [] } as never)

    await assignAppsToUser('user-1', ['app-1', 'app-2'])

    expect(request.post).toHaveBeenCalledWith('/admin/users/user-1/app-assignments', {
      body: { app_ids: ['app-1', 'app-2'] },
    })
  })

  it('revokes assignment', async () => {
    vi.mocked(request.post).mockResolvedValue({ id: 'assignment-1', status: 'revoked' } as never)

    await revokeUserAppAssignment('user-1', 'assignment-1')

    expect(request.post).toHaveBeenCalledWith('/admin/users/user-1/app-assignments/assignment-1/revoke')
  })
})
