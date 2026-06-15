import { describe, expect, it } from 'vitest'
import router, { getAdminAuthGuardRedirect, getAuthGuardRedirect, getCustomerConfigGuardRedirect } from '@/router'

describe('getAuthGuardRedirect', () => {
  it('allows public routes for anonymous users', () => {
    expect(
      getAuthGuardRedirect({
        routeName: 'pages-home',
        isLoggedIn: false,
      }),
    ).toBeNull()
  })

  it('allows anonymous users to access admin login after admin guard passes', () => {
    expect(
      getAuthGuardRedirect({
        routeName: 'admin-login',
        isLoggedIn: false,
      }),
    ).toBeNull()
  })

  it('allows anonymous users to access skills marketplace route', () => {
    expect(
      getAuthGuardRedirect({
        routeName: 'store-skills-list',
        isLoggedIn: false,
      }),
    ).toBeNull()
  })

  it('allows anonymous users to access login-prompt workspace routes', () => {
    expect(
      getAuthGuardRedirect({
        routeName: 'space-apps-list',
        isLoggedIn: false,
      }),
    ).toBeNull()

    expect(
      getAuthGuardRedirect({
        routeName: 'openapi-api-keys-list',
        isLoggedIn: false,
      }),
    ).toBeNull()
  })

  it('redirects anonymous users away from private workspace detail routes', () => {
    expect(
      getAuthGuardRedirect({
        routeName: 'space-apps-detail',
        isLoggedIn: false,
      }),
    ).toEqual({ path: '/home' })

    expect(
      getAuthGuardRedirect({
        routeName: 'space-workflows-detail',
        isLoggedIn: false,
      }),
    ).toEqual({ path: '/home' })
  })

  it('redirects anonymous users away from unnamed private routes by default', () => {
    expect(
      getAuthGuardRedirect({
        routeName: '',
        isLoggedIn: false,
      }),
    ).toEqual({ path: '/home' })
  })

  it('allows authenticated users to access private routes', () => {
    expect(
      getAuthGuardRedirect({
        routeName: 'space-apps-detail',
        isLoggedIn: true,
      }),
    ).toBeNull()
  })
})

describe('getCustomerConfigGuardRedirect', () => {
  it('redirects direct access to configuration routes for non-admin users', () => {
    expect(getCustomerConfigGuardRedirect({ path: '/space/apps', routeName: 'space-apps-list', isAdminLoggedIn: false })).toEqual({
      path: '/errors/403',
    })
    expect(getCustomerConfigGuardRedirect({ path: '/space/datasets/dataset-1/documents', routeName: 'space-datasets-documents-list', isAdminLoggedIn: false })).toEqual({
      path: '/errors/403',
    })
    expect(getCustomerConfigGuardRedirect({ path: '/openapi/api-keys', routeName: 'openapi-api-keys-list', isAdminLoggedIn: false })).toEqual({
      path: '/errors/403',
    })
  })

  it('allows logged-in admin users to access configuration routes', () => {
    expect(getCustomerConfigGuardRedirect({ path: '/space/apps', routeName: 'space-apps-list', isAdminLoggedIn: true })).toBeNull()
    expect(getCustomerConfigGuardRedirect({ path: '/space/datasets/dataset-1/documents', routeName: 'space-datasets-documents-list', isAdminLoggedIn: true })).toBeNull()
    expect(getCustomerConfigGuardRedirect({ path: '/openapi/api-keys', routeName: 'openapi-api-keys-list', isAdminLoggedIn: true })).toBeNull()
    expect(getCustomerConfigGuardRedirect({ path: '/space/apps?create_type=app', routeName: 'space-apps-list', isAdminLoggedIn: true })).toBeNull()
  })

  it('keeps store and public routes available to customers', () => {
    expect(getCustomerConfigGuardRedirect({ path: '/store/tools', routeName: 'store-tools-list', isAdminLoggedIn: false })).toBeNull()
    expect(getCustomerConfigGuardRedirect({ path: '/home', routeName: 'pages-home', isAdminLoggedIn: false })).toBeNull()
  })
})

describe('getAdminAuthGuardRedirect', () => {
  it('redirects anonymous admin users to admin login', () => {
    expect(
      getAdminAuthGuardRedirect({
        path: '/admin/apps',
        routeName: 'admin-apps',
        isAdminLoggedIn: false,
      }),
    ).toEqual({ path: '/auth/login', query: { mode: 'admin', redirect: '/admin/apps' } })
  })

  it('allows anonymous users to access admin login', () => {
    expect(
      getAdminAuthGuardRedirect({
        path: '/admin/login',
        routeName: 'admin-login',
        isAdminLoggedIn: false,
      }),
    ).toBeNull()
  })

  it('redirects logged-in admin users away from admin login', () => {
    expect(
      getAdminAuthGuardRedirect({
        path: '/admin/login',
        routeName: 'admin-login',
        isAdminLoggedIn: true,
      }),
    ).toEqual({ path: '/admin' })
  })

  it('requires both plan and redeem code read permissions for admin billing route', () => {
    const route = router.getRoutes().find((route) => route.name === 'admin-billing')

    expect(route?.meta.permissions).toEqual(['plan:read', 'redeem_code:read'])
  })

  it('allows logged-in admin users to access admin routes when permissions match', () => {
    expect(
      getAdminAuthGuardRedirect({
        path: '/admin/apps',
        routeName: 'admin-apps',
        isAdminLoggedIn: true,
        adminPermissions: ['app:read'],
        requiredPermissions: ['app:read'],
      }),
    ).toBeNull()
    expect(
      getAdminAuthGuardRedirect({
        path: '/admin/users',
        routeName: 'admin-users',
        isAdminLoggedIn: true,
        adminPermissions: ['user:read'],
        requiredPermissions: ['user:read'],
      }),
    ).toBeNull()
    expect(
      getAdminAuthGuardRedirect({
        path: '/admin/billing',
        routeName: 'admin-billing',
        isAdminLoggedIn: true,
        adminPermissions: ['plan:read', 'redeem_code:read'],
        requiredPermissions: ['plan:read', 'redeem_code:read'],
      }),
    ).toBeNull()
  })

  it('redirects admin billing users when either plan or redeem code read permission is missing', () => {
    expect(
      getAdminAuthGuardRedirect({
        path: '/admin/billing',
        routeName: 'admin-billing',
        isAdminLoggedIn: true,
        adminPermissions: ['plan:read'],
        requiredPermissions: ['plan:read', 'redeem_code:read'],
      }),
    ).toEqual({ path: '/errors/403' })
  })

  it('redirects logged-in admin users without required permissions to forbidden page', () => {
    expect(
      getAdminAuthGuardRedirect({
        path: '/admin/apps',
        routeName: 'admin-apps',
        isAdminLoggedIn: true,
        adminPermissions: ['workflow:read'],
        requiredPermissions: ['app:read'],
      }),
    ).toEqual({ path: '/errors/403' })
  })
})
