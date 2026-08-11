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
          path: 'studio',
          name: 'user-studio',
          component: () => import('@/views/studio/StudioPlaceholderView.vue'),
          meta: { requiresAuth: true },
        },
        {
          path: 'schedules',
          name: 'user-schedules',
          component: () => import('@/views/space/schedules/ListView.vue'),
          meta: { requiresAuth: true },
        },
        {
          path: 'schedules/runs/:task_id',
          name: 'user-schedules-runs',
          component: () => import('@/views/space/schedules/RunsView.vue'),
          meta: { requiresAuth: true },
        },
        {
          path: 'my-knowledge/:dataset_id/documents',
          name: 'space-datasets-documents-list',
          component: () => import('@/views/space/datasets/documents/ListView.vue'),
        },
        {
          path: 'my-knowledge/:dataset_id/documents/:document_id/segments',
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
          path: 'search',
          name: 'conversation-search',
          component: () => import('@/views/home/ConversationSearchView.vue'),
        },
        {
          path: 'memory',
          name: 'user-memory-graph',
          component: () => import('@/views/settings/MemoryView.vue'),
          meta: { requiresAuth: true },
        },
        {
          path: 'external-data-sources',
          name: 'user-external-data-sources-list',
          component: () => import('@/views/external-data-sources/ListView.vue'),
        },
        {
          path: 'showcase',
          name: 'showcase',
          component: () => import('@/views/showcase/ListView.vue'),
          meta: { requiresAuth: true },
        },
        {
          path: 'my-knowledge',
          name: 'my-knowledge',
          component: () => import('@/views/space/datasets/ListView.vue'),
          meta: { requiresAuth: true },
        },
        {
          path: 'membership',
          name: 'membership-index',
          component: () => import('@/views/membership/MembershipView.vue'),
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
          meta: { adminRequired: true, realm: 'admin' },
          children: [
            {
              path: '',
              name: 'admin-index',
              component: () => import('@/views/admin/AdminDashboardView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['admin:access'] },
            },
            {
              path: 'apps',
              name: 'admin-apps',
              component: () => import('@/views/admin/AppsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['app:read'] },
            },
            {
              path: 'workflows',
              name: 'admin-workflows',
              component: () => import('@/views/admin/AdminWorkflowsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['workflow:read'] },
            },
            {
              path: 'system-knowledge',
              name: 'admin-system-knowledge',
              component: () => import('@/views/admin/AdminSystemKnowledgeView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['system_knowledge:read'] },
            },
            {
              path: 'tools',
              name: 'admin-tools',
              component: () => import('@/views/admin/ToolsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['tool:read'] },
            },
            {
              path: 'mcp',
              name: 'admin-mcp',
              component: () => import('@/views/admin/AdminMcpView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['mcp:read'] },
            },
            {
              path: 'skills',
              name: 'admin-skills',
              component: () => import('@/views/admin/AdminSkillsView.vue'),
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
              path: 'cost-stats',
              name: 'admin-cost-stats',
              component: () => import('@/views/admin/CostDashboardView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['cost_stats:read'] },
            },
            {
              path: 'cost-strategy',
              name: 'admin-cost-strategy',
              component: () => import('@/views/admin/CostStrategyView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['model_pool:read'] },
            },
            {
              path: 'admin-users',
              name: 'admin-admin-users',
              component: () => import('@/views/admin/AdminUsersView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['admin_user:read'], roles: ['super_admin'] },
            },
            {
              path: 'roles',
              name: 'admin-roles',
              component: () => import('@/views/admin/RolesView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['role:read'], roles: ['super_admin'] },
            },
            {
              path: 'audit-logs',
              name: 'admin-audit-logs',
              component: () => import('@/views/admin/AuditLogsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['audit_log:read'], roles: ['super_admin'] },
            },
            {
              path: 'errors/403',
              name: 'admin-errors-forbidden',
              component: () => import('@/views/admin/AdminForbiddenView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin' },
            },
            {
              path: 'recycle-bin',
              name: 'admin-recycle-bin',
              component: () => import('@/views/admin/AdminRecycleBinView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['recycle_bin:read'], roles: ['super_admin'] },
            },
            {
              path: 'storage',
              name: 'admin-storage',
              component: () => import('@/views/admin/AdminStorageView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['storage:read'], roles: ['super_admin'] },
            },
            {
              path: 'routing-logs',
              name: 'admin-routing-logs',
              component: () => import('@/views/admin/RoutingLogsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['routing_log:read'] },
            },
            {
              path: 'orchestration-flags',
              name: 'admin-orchestration-flags',
              component: () => import('@/views/admin/OrchestrationFlagsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['orchestration_flag:read'] },
            },
            {
              path: 'routing-quality',
              name: 'admin-routing-quality',
              component: () => import('@/views/admin/RoutingQualityView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['routing_quality:read'] },
            },
            {
              path: 'routing-quality/suggestions',
              name: 'admin-routing-quality-suggestions',
              component: () => import('@/views/admin/routing-quality/SuggestionsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['routing_quality:read'] },
            },
            {
              path: 'apps/:app_id/edit',
              name: 'admin-app-edit',
              component: () => import('@/views/admin/apps/AdminAppDetailView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['app:read'], fluid: true },
            },
            {
              path: 'apps/:app_id/published',
              name: 'admin-app-published',
              component: () => import('@/views/admin/apps/AdminAppPublishedView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['app:read'] },
            },
            {
              path: 'apps/:app_id/analysis',
              name: 'admin-app-analysis',
              component: () => import('@/views/admin/apps/AdminAppAnalysisView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['app:read'] },
            },
            {
              path: 'apps/:app_id/versions',
              name: 'admin-app-versions',
              component: () => import('@/views/admin/apps/AdminAppVersionComparisonView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['app:read'] },
            },
            {
              path: 'apps/:app_id/prompt-compare',
              name: 'admin-app-prompt-compare',
              component: () => import('@/views/admin/apps/AdminAppPromptCompareView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['app:read'] },
            },
            {
              path: 'workflows/:workflow_id/edit',
              name: 'admin-workflow-edit',
              component: () => import('@/views/admin/workflows/AdminWorkflowDetailView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['workflow:read'], fluid: true },
            },
            {
              path: 'store/public-apps',
              name: 'admin-store-apps',
              component: () => import('@/views/admin/StoreAppsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['app:read'] },
            },
            {
              path: 'store/workflows',
              name: 'admin-store-workflows',
              component: () => import('@/views/admin/StoreWorkflowsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['workflow:read'] },
            },
            {
              path: 'store/workflows/:workflow_id/preview',
              name: 'admin-store-workflows-preview',
              component: () => import('@/views/store/workflows/PreviewView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['workflow:read'] },
            },
            {
              path: 'store/tools',
              name: 'admin-store-tools',
              component: () => import('@/views/admin/StoreToolsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['tool:read'] },
            },
            {
              path: 'store/skills',
              name: 'admin-store-skills',
              component: () => import('@/views/admin/StoreSkillsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['skill:read'] },
            },
            {
              path: 'store/mcp',
              name: 'admin-store-mcp',
              component: () => import('@/views/admin/StoreMcpView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['mcp:read'] },
            },
            {
              path: 'agent-pool',
              name: 'admin-agent-pool',
              component: () => import('@/views/admin/AgentPoolView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['agent_pool:read'] },
            },
            {
              path: 'sub-pool-definition',
              name: 'admin-sub-pool-definition',
              component: () => import('@/views/admin/sub-pool-definition/index.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['agent_pool:read'] },
            },
            {
              path: 'tool-governance',
              name: 'admin-tool-governance',
              component: () => import('@/views/admin/ToolGovernanceView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['tool_governance:read'] },
            },
            {
              path: 'models',
              name: 'admin-models',
              component: () => import('@/views/admin/ModelsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['model_pool:read'] },
            },
            {
              path: 'public-ai-features',
              name: 'admin-public-ai-features',
              component: () => import('@/views/admin/PublicAIFeatureConfigView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['model_pool:read'] },
            },
            {
              path: 'model-providers',
              name: 'AdminModelProviders',
              component: () => import('@/views/admin/ModelProvidersView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['model_provider:read'] },
            },
            {
              path: 'showcase',
              name: 'admin-showcase',
              component: () => import('@/views/admin/ShowcaseView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['showcase:read'] },
            },
            {
              path: 'openapi',
              name: 'admin-openapi',
              component: () => import('@/views/openapi/IndexView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['openapi:read'] },
            },
            {
              path: 'openapi/api-keys',
              name: 'admin-openapi-api-keys',
              component: () => import('@/views/openapi/api-keys/ListView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['openapi:read'] },
            },
            {
              path: 'schedules',
              name: 'admin-schedules',
              component: () => import('@/views/space/schedules/ListView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['admin:access'] },
            },
            {
              path: 'schedules/runs/:task_id',
              name: 'admin-schedules-runs',
              component: () => import('@/views/space/schedules/RunsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['admin:access'] },
            },
          ],
        },
        {
          path: 'auth/authorize/:provider_name',
          name: 'auth-authorize',
          component: () => import('@/views/auth/AuthorizeView.vue'),
        },
        {
          path: 'admin/login',
          name: 'admin-login',
          component: () => import('@/views/admin/LoginView.vue'),
          meta: { adminGuestOnly: true },
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
  'auth-login',
  'auth-authorize',
  'auth-forgot-password',
  'conversation-search',
  'errors-not-found',
  'errors-forbidden',
  'admin-login',
])

const ANONYMOUS_PROMPT_ROUTE_NAMES = new Set<string>()

export const getAuthGuardRedirect = ({
  path,
  routeName,
  isLoggedIn,
}: {
  path: string
  routeName: string
  isLoggedIn: boolean
}) => {
  if (isLoggedIn) return null
  if (path.startsWith('/admin')) return null
  if (PUBLIC_ROUTE_NAMES.has(routeName) || ANONYMOUS_PROMPT_ROUTE_NAMES.has(routeName)) {
    return null
  }

  return { path: '/home' as const }
}

export const shouldEvaluateUserAuth = (path: string): boolean => {
  return !path.startsWith('/admin')
}

const CUSTOMER_CONFIG_ROUTE_NAMES = new Set<string>()

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
  adminRoles = [],
  requiredPermissions,
  requiredRoles,
}: {
  path: string
  routeName: string
  isAdminLoggedIn: boolean
  adminPermissions?: string[]
  adminRoles?: string[]
  requiredPermissions?: string[]
  requiredRoles?: string[]
}) => {
  if (routeName === 'admin-login') {
    return isAdminLoggedIn ? { path: '/admin' as const } : null
  }
  if (!path.startsWith('/admin')) {
    return null
  }
  if (!isAdminLoggedIn) {
    return { path: '/admin/login' as const, query: { redirect: path } }
  }
  if (requiredRoles && requiredRoles.length > 0) {
    const hasRole = requiredRoles.some((role) => adminRoles.includes(role))
    if (!hasRole) {
      return { path: '/admin/errors/403' as const }
    }
  }
  if (requiredPermissions && requiredPermissions.length > 0) {
    const hasAll = requiredPermissions.every((permission) => adminPermissions.includes(permission))
    if (!hasAll) {
      return { path: '/admin/errors/403' as const }
    }
  }
  return null
}

router.beforeEach(async (to) => {
  const adminStore = useAdminStore()
  const path = to.fullPath

  // 已登录的管理员：每次导航前刷新资料/权限快照，保证新增权限
  // （如 storage:read）与角色调整即时生效，无需重新登录。
  // /admin/auth/me 失败（如 token 失效）时静默忽略，由下方守卫统一拦截。
  if (path.startsWith('/admin') && isAdminCredentialLoggedIn(getStoredAdminCredential())) {
    try {
      const { getCurrentAdmin } = await import('@/services/admin-auth')
      await getCurrentAdmin()
    } catch {
      /* 忽略，交由后续守卫处理 */
    }
  }

  const adminRedirect = getAdminAuthGuardRedirect({
    path,
    routeName: String(to.name || ''),
    isAdminLoggedIn: isAdminCredentialLoggedIn(getStoredAdminCredential()),
    adminPermissions: adminStore.admin.permissions,
    adminRoles: adminStore.admin.roles,
    requiredPermissions: to.meta?.permissions as string[] | undefined,
    requiredRoles: to.meta?.roles as string[] | undefined,
  })

  if (adminRedirect) {
    return adminRedirect
  }

  const customerConfigRedirect = getCustomerConfigGuardRedirect({
    path,
    routeName: String(to.name || ''),
    isAdminLoggedIn: isAdminCredentialLoggedIn(getStoredAdminCredential()),
  })

  if (customerConfigRedirect) {
    return customerConfigRedirect
  }

  const redirect = getAuthGuardRedirect({
    path,
    routeName: String(to.name || ''),
    isLoggedIn: shouldEvaluateUserAuth(path) ? auth.isLogin() : false,
  })

  if (redirect) {
    return redirect
  }
})

const DEFAULT_PAGE_TITLE = '钰心AI'
const ADMIN_PAGE_TITLE = '钰心Admin'

router.afterEach((to) => {
  if (typeof document === 'undefined') return
  document.title = to.path.startsWith('/admin') ? ADMIN_PAGE_TITLE : DEFAULT_PAGE_TITLE
})

export default router
