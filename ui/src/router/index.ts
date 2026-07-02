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
        {
          path: 'memory',
          name: 'user-memory-list',
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
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/pages/SettingsView.vue'),
          meta: { requiresAuth: true },
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
              path: 'datasets',
              name: 'admin-datasets',
              component: () => import('@/views/admin/AdminDatasetsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['dataset:read'] },
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
              component: () => import('@/views/space/apps/DetailView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['app:read'] },
            },
            {
              path: 'apps/:app_id/published',
              name: 'admin-app-published',
              component: () => import('@/views/space/apps/PublishedView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['app:read'] },
            },
            {
              path: 'apps/:app_id/analysis',
              name: 'admin-app-analysis',
              component: () => import('@/views/space/apps/AnalysisView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['app:read'] },
            },
            {
              path: 'apps/:app_id/versions',
              name: 'admin-app-versions',
              component: () => import('@/views/space/apps/VersionComparisonView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['app:read'] },
            },
            {
              path: 'apps/:app_id/prompt-compare',
              name: 'admin-app-prompt-compare',
              component: () => import('@/views/space/apps/PromptCompareView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['app:read'] },
            },
            {
              path: 'workflows/:workflow_id/edit',
              name: 'admin-workflow-edit',
              component: () => import('@/views/space/workflows/DetailView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['workflow:read'] },
            },
            {
              path: 'datasets/list',
              name: 'admin-dataset-list',
              component: () => import('@/views/space/datasets/ListView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['dataset:read'] },
            },
            {
              path: 'datasets/:dataset_id/documents',
              name: 'admin-dataset-documents',
              component: () => import('@/views/admin/AdminDatasetDocumentsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['dataset:read'] },
            },
            {
              path: 'datasets/:dataset_id/documents/create',
              name: 'admin-dataset-document-create',
              component: () => import('@/views/admin/AdminDatasetDocumentCreateView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['dataset:read'] },
            },
            {
              path: 'datasets/:dataset_id/documents/:document_id/segments',
              name: 'admin-dataset-segments',
              component: () => import('@/views/admin/AdminDatasetSegmentsView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['dataset:read'] },
            },
            {
              path: 'tools/list',
              name: 'admin-tool-list',
              component: () => import('@/views/space/tools/ListView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['tool:read'] },
            },
            {
              path: 'mcp/list',
              name: 'admin-mcp-list',
              component: () => import('@/views/space/mcp/ListView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['mcp:read'] },
            },
            {
              path: 'store/public-apps',
              name: 'admin-store-apps',
              component: () => import('@/views/store/public-apps/ListView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['app:read'] },
            },
            {
              path: 'store/workflows',
              name: 'admin-store-workflows',
              component: () => import('@/views/store/workflows/ListView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['workflow:read'] },
            },
            {
              path: 'store/tools',
              name: 'admin-store-tools',
              component: () => import('@/views/store/tools/ListView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['tool:read'] },
            },
            {
              path: 'store/skills',
              name: 'admin-store-skills',
              component: () => import('@/views/store/skills/ListView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['skill:read'] },
            },
            {
              path: 'store/mcp',
              name: 'admin-store-mcp',
              component: () => import('@/views/store/mcp/ListView.vue'),
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
          component: () => import('@/views/admin/LoginView.vue'),
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

const CUSTOMER_CONFIG_ROUTE_NAMES = new Set([
  'space-apps-list',
  'space-tools-list',
  'space-workflows-list',
  'space-mcp-list',
  'space-datasets-list',
  'space-datasets-documents-list',
  'space-datasets-documents-create',
  'space-datasets-documents-segments-list',
  'space-apps-detail',
  'space-apps-published',
  'space-apps-analysis',
  'space-apps-versions',
  'space-apps-prompt-compare',
  'space-workflows-detail',
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
      return { path: '/errors/403' as const }
    }
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
  const path = to.fullPath
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
export default router
