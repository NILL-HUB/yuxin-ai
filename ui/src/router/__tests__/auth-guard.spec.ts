import { describe, expect, it } from 'vitest'
import router, {
  getAdminAuthGuardRedirect,
  getAuthGuardRedirect,
  getCustomerConfigGuardRedirect,
  shouldEvaluateUserAuth,
} from '@/router'

describe('getAuthGuardRedirect', () => {
  it('skips user auth evaluation for admin routes', () => {
    expect(shouldEvaluateUserAuth('/admin')).toBe(false)
    expect(shouldEvaluateUserAuth('/admin/apps')).toBe(false)
    expect(shouldEvaluateUserAuth('/admin/store/public-apps')).toBe(false)
    expect(shouldEvaluateUserAuth('/home')).toBe(true)
  })

  it('allows public routes for anonymous users', () => {
    expect(
      getAuthGuardRedirect({
        path: '/home',
        routeName: 'pages-home',
        isLoggedIn: false,
      }),
    ).toBeNull()
  })

  it('allows anonymous users to access admin login after admin guard passes', () => {
    expect(
      getAuthGuardRedirect({
        path: '/admin/login',
        routeName: 'admin-login',
        isLoggedIn: false,
      }),
    ).toBeNull()
  })

  it('skips user auth guard for admin paths even when user is not logged in', () => {
    expect(
      getAuthGuardRedirect({
        path: '/admin',
        routeName: 'admin-index',
        isLoggedIn: false,
      }),
    ).toBeNull()

    expect(
      getAuthGuardRedirect({
        path: '/admin/users',
        routeName: 'admin-users',
        isLoggedIn: false,
      }),
    ).toBeNull()
  })

  it('allows anonymous users to access skills marketplace route', () => {
    expect(
      getAuthGuardRedirect({
        path: '/store/skills',
        routeName: 'store-skills-list',
        isLoggedIn: false,
      }),
    ).toBeNull()
  })

  it('allows anonymous users to access public store and search routes', () => {
    expect(
      getAuthGuardRedirect({
        path: '/store/public-apps',
        routeName: 'store-public-apps-list',
        isLoggedIn: false,
      }),
    ).toBeNull()

    expect(
      getAuthGuardRedirect({
        path: '/search',
        routeName: 'conversation-search',
        isLoggedIn: false,
      }),
    ).toBeNull()
  })

  it('redirects anonymous users away from private user routes', () => {
    expect(
      getAuthGuardRedirect({
        path: '/schedules',
        routeName: 'user-schedules',
        isLoggedIn: false,
      }),
    ).toEqual({ path: '/home' })

    expect(
      getAuthGuardRedirect({
        path: '/my-knowledge',
        routeName: 'my-knowledge',
        isLoggedIn: false,
      }),
    ).toEqual({ path: '/home' })
  })

  it('redirects anonymous users away from unnamed private routes by default', () => {
    expect(
      getAuthGuardRedirect({
        path: '/some/private/page',
        routeName: '',
        isLoggedIn: false,
      }),
    ).toEqual({ path: '/home' })
  })

  it('allows authenticated users to access private routes', () => {
    expect(
      getAuthGuardRedirect({
        path: '/schedules',
        routeName: 'user-schedules',
        isLoggedIn: true,
      }),
    ).toBeNull()
  })
})

describe('getCustomerConfigGuardRedirect', () => {
  it('does not block non-admin users from regular user routes', () => {
    expect(getCustomerConfigGuardRedirect({ path: '/schedules', routeName: 'user-schedules', isAdminLoggedIn: false })).toBeNull()
    expect(getCustomerConfigGuardRedirect({ path: '/search', routeName: 'conversation-search', isAdminLoggedIn: false })).toBeNull()
    expect(getCustomerConfigGuardRedirect({ path: '/my-knowledge', routeName: 'my-knowledge', isAdminLoggedIn: false })).toBeNull()
  })

  it('blocks non-admin users from routes carrying a create_type query', () => {
    expect(getCustomerConfigGuardRedirect({ path: '/store/public-apps?create_type=app', routeName: 'store-public-apps-list', isAdminLoggedIn: false })).toEqual({
      path: '/errors/403',
    })
  })

  it('allows admin users to access user routes even with create_type query', () => {
    expect(getCustomerConfigGuardRedirect({ path: '/store/public-apps?create_type=app', routeName: 'store-public-apps-list', isAdminLoggedIn: true })).toBeNull()
  })

  it('allows non-admin users to access non-config routes', () => {
    expect(getCustomerConfigGuardRedirect({ path: '/store/tools', routeName: 'store-tools-list', isAdminLoggedIn: false })).toBeNull()
    expect(getCustomerConfigGuardRedirect({ path: '/home', routeName: 'pages-home', isAdminLoggedIn: false })).toBeNull()
  })
})

describe('getAdminAuthGuardRedirect', () => {
  it('redirects unauthenticated admin route access to admin login', () => {
    expect(
      getAdminAuthGuardRedirect({
        path: '/admin/apps',
        routeName: 'admin-apps',
        isAdminLoggedIn: false,
      }),
    ).toEqual({ path: '/admin/login', query: { redirect: '/admin/apps' } })
  })

  it('redirects logged-in admin away from admin login page', () => {
    expect(
      getAdminAuthGuardRedirect({
        path: '/admin/login',
        routeName: 'admin-login',
        isAdminLoggedIn: true,
      }),
    ).toEqual({ path: '/admin' })
  })

  it('allows logged-in admin to access admin pages', () => {
    expect(
      getAdminAuthGuardRedirect({
        path: '/admin/apps',
        routeName: 'admin-apps',
        isAdminLoggedIn: true,
      }),
    ).toBeNull()
  })

  it('returns 403 when admin lacks required role', () => {
    expect(
      getAdminAuthGuardRedirect({
        path: '/admin/users',
        routeName: 'admin-users',
        isAdminLoggedIn: true,
        requiredRoles: ['super_admin'],
        adminRoles: ['viewer'],
      }),
    ).toEqual({ path: '/errors/403' })
  })

  it('returns 403 when admin lacks required permission', () => {
    expect(
      getAdminAuthGuardRedirect({
        path: '/admin/billing',
        routeName: 'admin-billing',
        isAdminLoggedIn: true,
        requiredPermissions: ['billing:manage'],
        adminPermissions: [],
      }),
    ).toEqual({ path: '/errors/403' })
  })

  it('allows access when admin has required permission', () => {
    expect(
      getAdminAuthGuardRedirect({
        path: '/admin/billing',
        routeName: 'admin-billing',
        isAdminLoggedIn: true,
        requiredPermissions: ['billing:manage'],
        adminPermissions: ['billing:manage'],
      }),
    ).toBeNull()
  })

  it('returns 403 when admin lacks at least one required permission', () => {
    expect(
      getAdminAuthGuardRedirect({
        path: '/admin/apps',
        routeName: 'admin-apps',
        isAdminLoggedIn: true,
        requiredPermissions: ['app:read', 'app:manage'],
        adminPermissions: ['app:read'],
      }),
    ).toEqual({ path: '/errors/403' })
  })
})

describe('router', () => {
  it('is defined', () => {
    expect(router).toBeDefined()
  })
})
