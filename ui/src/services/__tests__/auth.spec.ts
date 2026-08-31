import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  emailCodeLogin,
  getLoginMethods,
  logout,
  passwordLogin,
  phoneCodeLogin,
  phoneRegisterRequest,
  phoneRegisterVerify,
  prepareRegister,
  resendLoginChallenge,
  resetPassword,
  sendCode,
  sendResetCode,
  verifyLoginChallenge,
  verifyRegister,
} from '@/services/auth'
import * as request from '@/utils/request'
import * as auth from '@/utils/auth'

vi.mock('@/utils/request', () => ({
  post: vi.fn(),
  get: vi.fn(),
}))

vi.mock('@/utils/auth', () => ({
  getCredentialSessionId: vi.fn(),
  getStoredCredential: vi.fn(),
}))

describe('auth service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(auth.getCredentialSessionId).mockReturnValue('')
    vi.mocked(request.post).mockResolvedValue({ data: {}, message: 'ok' } as never)
  })

  it('posts password login credentials to the auth endpoint', async () => {
    await passwordLogin('AtlasUser1', 'Abcd_1234')

    expect(request.post).toHaveBeenCalledWith('/auth/password-login', {
      body: {
        identifier: 'AtlasUser1',
        password: 'Abcd_1234',
      },
    })
  })

  it('posts register prepare and verify requests to the expected endpoints', async () => {
    await prepareRegister('AtlasUser1', 'tester@example.com', 'Abcd_1234')
    await verifyRegister('AtlasUser1', 'tester@example.com', 'Abcd_1234', '123456')

    expect(request.post).toHaveBeenNthCalledWith(1, '/auth/register/prepare', {
      body: {
        username: 'AtlasUser1',
        email: 'tester@example.com',
        password: 'Abcd_1234',
      },
    })
    expect(request.post).toHaveBeenNthCalledWith(2, '/auth/register/verify', {
      body: {
        username: 'AtlasUser1',
        email: 'tester@example.com',
        password: 'Abcd_1234',
        code: '123456',
      },
    })
  })

  it('posts reset-password requests to the expected endpoints', async () => {
    await sendResetCode('tester@example.com')
    await resetPassword('tester@example.com', '123456', 'NewPass123')

    expect(request.post).toHaveBeenNthCalledWith(1, '/auth/send-reset-code', {
      body: { email: 'tester@example.com' },
    })
    expect(request.post).toHaveBeenNthCalledWith(2, '/auth/reset-password', {
      body: {
        email: 'tester@example.com',
        code: '123456',
        new_password: 'NewPass123',
      },
    })
  })

  it('posts login challenge verify and resend requests to the expected endpoints', async () => {
    await verifyLoginChallenge('challenge-1', '654321')
    await resendLoginChallenge('challenge-1')

    expect(request.post).toHaveBeenNthCalledWith(1, '/auth/login-challenge/verify', {
      body: {
        challenge_id: 'challenge-1',
        code: '654321',
      },
    })
    expect(request.post).toHaveBeenNthCalledWith(2, '/auth/login-challenge/resend', {
      body: {
        challenge_id: 'challenge-1',
      },
    })
  })

  it('passes the channel along when verifying or resending a login challenge', async () => {
    await verifyLoginChallenge('challenge-1', '654321', 'phone')
    await resendLoginChallenge('challenge-1', 'email')

    expect(request.post).toHaveBeenNthCalledWith(1, '/auth/login-challenge/verify', {
      body: {
        challenge_id: 'challenge-1',
        code: '654321',
        channel: 'phone',
      },
    })
    expect(request.post).toHaveBeenNthCalledWith(2, '/auth/login-challenge/resend', {
      body: {
        challenge_id: 'challenge-1',
        channel: 'email',
      },
    })
  })

  it('fetches login methods from the auth endpoint', async () => {
    await getLoginMethods()

    expect(request.get).toHaveBeenCalledWith('/auth/login-methods')
  })

  it('posts unified send-code requests with scene and target payloads', async () => {
    await sendCode({ scene: 'phone_login', phone: '13800138000' })
    await sendCode({ scene: 'login_challenge', challenge_id: 'c-1', channel: 'phone' })

    expect(request.post).toHaveBeenNthCalledWith(1, '/auth/send-code', {
      body: { scene: 'phone_login', phone: '13800138000' },
    })
    expect(request.post).toHaveBeenNthCalledWith(2, '/auth/send-code', {
      body: { scene: 'login_challenge', challenge_id: 'c-1', channel: 'phone' },
    })
  })

  it('posts phone and email code logins to the expected endpoints', async () => {
    await phoneCodeLogin('13800138000', '123456')
    await emailCodeLogin('tester@example.com', '123456')

    expect(request.post).toHaveBeenNthCalledWith(1, '/auth/phone-code-login', {
      body: { phone: '13800138000', code: '123456' },
    })
    expect(request.post).toHaveBeenNthCalledWith(2, '/auth/email-code-login', {
      body: { email: 'tester@example.com', code: '123456' },
    })
  })

  it('posts phone registration prepare and verify requests to the expected endpoints', async () => {
    await phoneRegisterRequest('13800138000')
    await phoneRegisterVerify('13800138000', '654321', {
      username: 'PhoneUser',
      password: 'Abcd1234',
    })

    expect(request.post).toHaveBeenNthCalledWith(1, '/auth/register/phone-prepare', {
      body: { phone: '13800138000' },
    })
    expect(request.post).toHaveBeenNthCalledWith(2, '/auth/register/phone-verify', {
      body: {
        phone: '13800138000',
        code: '654321',
        username: 'PhoneUser',
        password: 'Abcd1234',
      },
    })
  })

  it('posts logout without a session id for legacy credentials', async () => {
    await logout()

    expect(request.post).toHaveBeenCalledWith('/auth/logout')
  })

  it('passes the current session id to logout so the device is revoked', async () => {
    vi.mocked(auth.getCredentialSessionId).mockReturnValue('session-current')

    await logout()

    expect(request.post).toHaveBeenCalledWith('/auth/logout', {
      params: { session_id: 'session-current' },
    })
  })
})
