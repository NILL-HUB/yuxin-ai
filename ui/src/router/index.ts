import { createRouter, createWebHistory } from 'vue-router'
import auth from '@/utils/auth'
import { getStoredAdminCredential, isAdminCredentialLoggedIn } from '@/utils/admin-auth'
import { useAdminStore } from '@/stores/admin'
import DefaultLayout from '@/views/layouts/DefaultLayout.vue'
import BlankLayout from '@/views/layouts/BlankLayout.vue'
import AdminLayout from '@/layouts/AdminLayout.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      component: DefaultLayout,
      children: [
        {
          path: '',
          redirect: 'home',
        },
        {
          path: 'home',
          name: 'pages-home',
          component: () => import('@/views/pages/HomeView.vue'),
        },
        {
          path: 'space',
          component: () => import('@/views/space/SpaceLayoutView.vue'),
          children: [
            {
              path: 'apps',
              name: 'space-apps-list',
              component: () => import('@/views/space/apps/ListView.vue'),
            },
            {
              path: 'tools',
              name: 'space-tools-list',
              component: () => import('@/views/space/tools/ListView.vue'),
            },
            {
              path: 'workflows',
              name: 'space-workflows-list',
              component: () => import('@/views/space/workflows/ListView.vue'),
            },
            {
              path: 'mcp',
              name: 'space-mcp-list',
              component: () => import('@/views/space/mcp/ListView.vue'),
            },
            {
              path: 'datasets',
              name: 'space-datasets-list',
              component: () => import('@/views/space/datasets/ListView.vue'),
            },
          ],
        },
        {
          path: 'space/datasets/:dataset_id/documents',
          name: 'space-datasets-documents-list',
          component: () => import('@/views/space/datasets/documents/ListView.vue'),
        },
        {
          path: 'space/datasets/:dataset_id/documents/create',
          name: 'space-datasets-documents-create',
          component: () => import('@/views/space/datasets/documents/CreateView.vue'),
        },
        {
          path: 'space/datasets/:dataset_id/documents/:document_id/segments',
          name: 'space-datasets-documents-segments-list',
          component: () => import('@/views/space/datasets/documents/segments/ListView.vue'),
        },
        {
          path: 'store/public-apps',
          name: 'store-public-apps-list',
          component: () => import('@/views/store/public-apps/ListView.vue'),
        },
        {
          path: 'store/public-apps/:app_id',
          component: () => import('@/views/store/public-apps/AppPreviewLayoutView.vue'),
          children: [
            {
              path: 'preview',
              name: 'store-public-apps-preview',
              component: () => import('@/views/store/public-apps/AppPreviewDetailView.vue'),
            },
          ],
        },
        {
          path: 'store/tools',
          name: 'store-tools-list',
          component: () => import('@/views/store/tools/ListView.vue'),
        },
        {
          path: 'store/skills',
          name: 'store-skills-list',
          component: () => import('@/views/store/skills/ListView.vue'),
        },
        {
          path: 'store/mcp',
          name: 'store-mcp-list',
          component: () => import('@/views/store/mcp/ListView.vue'),
        },
        {
          path: 'store/workflows',
          name: 'store-workflows-list',
          component: () => import('@/views/store/workflows/ListView.vue'),
        },
        {
          path: 'store/workflows/:workflow_id/preview',
          name: 'store-workflows-preview',
          component: () => import('@/views/store/workflows/PreviewView.vue'),
        },
        {
          path: 'search',
          name: 'conversation-search',
          component: () => import('@/views/home/ConversationSearchView.vue'),
        },
        {
          path: 'my-ai',
          name: 'my-ai-index',
          component: () => import('@/views/my-ai/MyAiView.vue'),
        },
        {
          path: 'my-ai/:app_id',
          name: 'my-ai-chat',
          component: () => import('@/views/my-ai/MyAiChatView.vue'),
        },
        {
          path: 'openapi',
          component: () => import('@/views/openapi/OpenAPILayoutView.vue'),
          children: [
            {
              path: '',
              name: 'openapi-index',
              component: () => import('@/views/openapi/IndexView.vue'),
            },
            {
              path: 'api-keys',
              name: 'openapi-api-keys-list',
              component: () => import('@/views/openapi/api-keys/ListView.vue'),
            },
          ],
        },
      ],
    },
    {
      path: '/',
      component: BlankLayout,
      children: [
        {
          path: 'auth/login',
          name: 'auth-login',
          component: () => import('@/views/auth/LoginView.vue'),
        },
        {
          path: 'auth/forgot-password',
          name: 'auth-forgot-password',
          redirect: '/home',
        },
        {
          path: 'admin',
          component: AdminLayout,
          meta: { adminRequired: true, requiresAuth: true, realm: 'admin' },
          children: [
            {
              path: '',
              name: 'admin-index',
              component: { template: '<h2 style="padding:60px 0;font-size:28px;letter-spacing:-0.04em">管理控制台</h2>' },
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['admin:access'] },
            },
            {
              path: 'apps',
              name: 'admin-apps',
              component: { template: '<h2>应用管理</h2>' },
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['app:read'] },
            },
            {
              path: 'workflows',
              name: 'admin-workflows',
              component: { template: '<h2>工作流管理</h2>' },
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['workflow:read'] },
            },
            {
              path: 'datasets',
              name: 'admin-datasets',
              component: { template: '<h2>知识库</h2>' },
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['dataset:read'] },
            },
            {
              path: 'tools',
              name: 'admin-tools',
              component: { template: '<h2>工具管理</h2>' },
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['tool:read'] },
            },
            {
              path: 'mcp',
              name: 'admin-mcp',
              component: { template: '<h2>MCP 管理</h2>' },
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['mcp:read'] },
            },
            {
              path: 'skills',
              name: 'admin-skills',
              component: { template: '<h2>Skills 管理</h2>' },
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['skill:read'] },
            },
            {
              path: 'users',
              name: 'admin-users',
              component: () => import('@/views/admin/CustomerUsersView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['user:read'] },
            },
            {
              path: 'billing',
              name: 'admin-billing',
              component: () => import('@/views/admin/BillingView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['plan:read', 'redeem_code:read'] },
            },
            {
              path: 'admin-users',
              name: 'admin-admin-users',
              component: { template: '<h2>管理员管理</h2>' },
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['admin_user:read'] },
            },
            {
              path: 'roles',
              name: 'admin-roles',
              component: { template: '<h2>角色权限</h2>' },
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['role:read'] },
            },
            {
              path: 'audit-logs',
              name: 'admin-audit-logs',
              component: { template: '<h2>审计日志</h2>' },
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['audit_log:read'] },
            },
          ],
        },
        {
          path: 'auth/authorize/:provider_name',
          name: 'auth-authorize',
          component: () => import('@/views/auth/AuthorizeView.vue'),
        },
        {
          path: 'membership',
          name: 'membership-index',
          component: () => import('@/views/membership/MembershipView.vue'),
        },
        {
          path: 'admin/login',
          name: 'admin-login',
          redirect: { path: '/auth/login', query: { mode: 'admin' } },
          meta: { adminGuestOnly: true },
        },
        {
          path: 'space/apps',
          component: () => import('@/views/space/apps/AppLayoutView.vue'),
          children: [
            {
              path: ':app_id',
              name: 'space-apps-detail',
              component: () => import('@/views/space/apps/DetailView.vue'),
            },
            {
              path: ':app_id/published',
              name: 'space-apps-published',
              component: () => import('@/views/space/apps/PublishedView.vue'),
            },
            {
              path: ':app_id/analysis',
              name: 'space-apps-analysis',
              component: () => import('@/views/space/apps/AnalysisView.vue'),
            },
            {
              path: ':app_id/versions',
              name: 'space-apps-versions',
              component: () => import('@/views/space/apps/VersionComparisonView.vue'),
            },
            {
              path: ':app_id/prompt-compare',
              name: 'space-apps-prompt-compare',
              component: () => import('@/views/space/apps/PromptCompareView.vue'),
            },
          ],
        },
        {
          path: 'space/workflows/:workflow_id',
          name: 'space-workflows-detail',
          component: () => import('@/views/space/workflows/DetailView.vue'),
        },
        {
          path: 'web-apps/:token',
          name: 'web-apps-index',
          component: () => import('@/views/web-apps/IndexView.vue'),
        },
        {
          path: '/errors/404',
          name: 'errors-not-found',
          component: () => import('@/views/errors/NotFoundView.vue'),
        },
        {
          path: '/errors/403',
          name: 'errors-forbidden',
          component: () => import('@/views/errors/ForbiddenView.vue'),
        },
        {
          path: '/:pathMatch(.*)*',
          redirect: '/errors/404' // 或者直接渲染404组件
        }
      ],
    },
  ],
})

const PUBLIC_ROUTE_NAMES = new Set([
  'pages-home',
  'web-apps-index',
  'store-public-apps-list',
  'store-public-apps-preview',
  'store-tools-list',
  'store-skills-list',
  'store-mcp-list',
  'store-workflows-list',
  'store-workflows-preview',
  'auth-login',
  'auth-authorize',
  'auth-forgot-password',
  'openapi-index',
  'conversation-search',
  'errors-not-found',
  'errors-forbidden',
  'admin-login',
])

const ANONYMOUS_PROMPT_ROUTE_NAMES = new Set([
  'space-apps-list',
  'space-tools-list',
  'space-workflows-list',
  'space-mcp-list',
  'space-datasets-list',
  'openapi-api-keys-list',
])

export const getAuthGuardRedirect = ({
  routeName,
  isLoggedIn,
}: {
  routeName: string
  isLoggedIn: boolean
}) => {
  if (isLoggedIn) return null
  if (PUBLIC_ROUTE_NAMES.has(routeName) || ANONYMOUS_PROMPT_ROUTE_NAMES.has(routeName)) {
    return null
  }

  return { path: '/home' as const }
}

const CUSTOMER_CONFIG_ROUTE_NAMES = new Set([
  'space-apps-list',
  'space-tools-list',
  'space-workflows-list',
  'space-mcp-list',
  'space-datasets-list',
  'space-datasets-documents-list',
  'space-datasets-documents-create',
  'space-datasets-documents-segments-list',
  'openapi-api-keys-list',
])

export const getCustomerConfigGuardRedirect = ({
  path,
  routeName,
  isAdminLoggedIn,
}: {
  path: string
  routeName: string
  isAdminLoggedIn: boolean
}) => {
  if (isAdminLoggedIn) {
    return null
  }
  if (CUSTOMER_CONFIG_ROUTE_NAMES.has(routeName)) {
    return { path: '/errors/403' as const }
  }
  if (path.includes('create_type=')) {
    return { path: '/errors/403' as const }
  }
  return null
}

export const getAdminAuthGuardRedirect = ({
  path,
  routeName,
  isAdminLoggedIn,
  adminPermissions = [],
  requiredPermissions,
}: {
  path: string
  routeName: string
  isAdminLoggedIn: boolean
  adminPermissions?: string[]
  requiredPermissions?: string[]
}) => {
  if (routeName === 'admin-login') {
    return isAdminLoggedIn ? { path: '/admin' as const } : null
  }
  if (!path.startsWith('/admin')) {
    return null
  }
  if (!isAdminLoggedIn) {
    return { path: '/auth/login' as const, query: { mode: 'admin', redirect: path } }
  }
  if (requiredPermissions && requiredPermissions.length > 0) {
    const hasAll = requiredPermissions.every((permission) => adminPermissions.includes(permission))
    if (!hasAll) {
      return { path: '/errors/403' as const }
    }
  }
  return null
}

router.beforeEach(async (to) => {
  const adminStore = useAdminStore()
  const adminRedirect = getAdminAuthGuardRedirect({
    path: to.fullPath,
    routeName: String(to.name || ''),
    isAdminLoggedIn: isAdminCredentialLoggedIn(getStoredAdminCredential()),
    adminPermissions: adminStore.admin.permissions,
    requiredPermissions: to.meta?.permissions as string[] | undefined,
  })

  if (adminRedirect) {
    return adminRedirect
  }

  const customerConfigRedirect = getCustomerConfigGuardRedirect({
    path: to.fullPath,
    routeName: String(to.name || ''),
    isAdminLoggedIn: isAdminCredentialLoggedIn(getStoredAdminCredential()),
  })

  if (customerConfigRedirect) {
    return customerConfigRedirect
  }

  const redirect = getAuthGuardRedirect({
    routeName: String(to.name || ''),
    isLoggedIn: auth.isLogin(),
  })

  if (redirect) {
    return redirect
  }
})
export default router
