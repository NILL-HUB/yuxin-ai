<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import { adminChangePassword, adminLogout } from '@/services/admin-auth'
import { useAdminStore } from '@/stores/admin'
import storage from '@/utils/storage'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const adminStore = useAdminStore()

// 编辑器路由（工作流/应用编排画布）需要 fluid 布局：取消 padding，让画布填满 topbar 下方区域
const isFluidRoute = computed(() => Boolean(route.meta.fluid))
const passwordModalVisible = ref(false)
const passwordLoading = ref(false)
const passwordForm = ref({ currentPassword: '', newPassword: '', confirmPassword: '' })

const collapsed = ref(storage.get('admin_sidebar_collapsed', false))
const toggleSidebar = () => {
  collapsed.value = !collapsed.value
}
watch(collapsed, (val) => storage.set('admin_sidebar_collapsed', val))

const _storedGroups = storage.get('admin_expanded_groups', null) as string[] | null
const expandedGroups = ref<Set<string> | null>(
  _storedGroups === null ? null : new Set(_storedGroups)
)
const isGroupExpanded = (title: string) => {
  if (expandedGroups.value === null) return true
  return expandedGroups.value.has(title)
}
const toggleGroup = (title: string) => {
  if (collapsed.value) return
  const set = new Set(expandedGroups.value || [])
  if (set.has(title)) {
    set.delete(title)
  } else {
    set.add(title)
  }
  expandedGroups.value = set
  storage.set('admin_expanded_groups', Array.from(set))
}

type MenuItem = {
  to: string
  label: string
  permission?: string
  permissions?: string[]
  roles?: string[]
}

type MenuGroup = {
  title: string
  icon: string
  items: MenuItem[]
}

const menuGroups = computed(() => ([
  {
    title: t('admin.adminLayout.menu.overview'),
    icon: 'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z',
    items: [
      { to: '/admin', label: t('admin.adminLayout.menu.dashboard'), permission: 'admin:access' },
    ],
  },
  {
    title: t('admin.adminLayout.menu.rbacManagement'),
    icon: 'M12 2L4 5v6c0 5 3.5 9.5 8 11 4.5-1.5 8-6 8-11V5l-8-3z',
    items: [
      { to: '/admin/admin-users', label: t('admin.adminLayout.menu.adminUsers'), permission: 'admin_user:read' },
      { to: '/admin/roles', label: t('admin.adminLayout.menu.roles'), permission: 'role:read' },
      { to: '/admin/users', label: t('admin.adminLayout.menu.customerUsers'), permission: 'user:read' },
    ],
  },
  {
    title: t('admin.adminLayout.menu.resourceOrchestration'),
    icon: 'M3 7l9-4 9 4-9 4-9-4zM3 12l9 4 9-4M3 17l9 4 9-4',
    items: [
      { to: '/admin/apps', label: t('admin.adminLayout.menu.apps'), permission: 'app:read' },
      { to: '/admin/workflows', label: t('admin.adminLayout.menu.workflows'), permission: 'workflow:read' },
      { to: '/admin/system-knowledge', label: t('admin.adminLayout.menu.systemKnowledge'), permission: 'system_knowledge:read' },
      { to: '/admin/tools', label: t('admin.adminLayout.menu.tools'), permission: 'tool:read' },
      { to: '/admin/mcp', label: t('admin.adminLayout.menu.mcp'), permission: 'mcp:read' },
      { to: '/admin/skills', label: t('admin.adminLayout.menu.skills'), permission: 'skill:read' },
    ],
  },
  {
    title: t('admin.adminLayout.menu.resourceOps'),
    icon: 'M3 9l1-5h16l1 5M5 9v11h14V9M9 14h6',
    items: [
      { to: '/admin/store/public-apps', label: t('admin.adminLayout.menu.appStore'), permission: 'app:read' },
      { to: '/admin/store/workflows', label: t('admin.adminLayout.menu.workflowStore'), permission: 'workflow:read' },
      { to: '/admin/store/tools', label: t('admin.adminLayout.menu.toolStore'), permission: 'tool:read' },
      { to: '/admin/store/skills', label: t('admin.adminLayout.menu.skillStore'), permission: 'skill:read' },
      { to: '/admin/store/mcp', label: t('admin.adminLayout.menu.mcpStore'), permission: 'mcp:read' },
    ],
  },
  {
    title: t('admin.adminLayout.menu.poolGovernance'),
    icon: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
    items: [
      { to: '/admin/agent-pool', label: t('admin.adminLayout.menu.agentPool'), permission: 'agent_pool:read' },
      { to: '/admin/tool-governance', label: t('admin.adminLayout.menu.toolGovernance'), permission: 'tool_governance:read' },
      { to: '/admin/sub-pool-definition', label: t('admin.adminLayout.menu.subPoolDef'), permission: 'agent_pool:read' },
      { to: '/admin/model-providers', label: t('admin.adminLayout.menu.modelProviders'), permission: 'model_provider:read' },
      { to: '/admin/models', label: t('admin.adminLayout.menu.models'), permission: 'model_pool:read' },
      { to: '/admin/public-ai-features', label: t('admin.adminLayout.menu.publicAIFeatures'), permission: 'model_pool:read' },
    ],
  },
  {
    title: t('admin.adminLayout.menu.observability'),
    icon: 'M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7zM12 9a3 3 0 100 6 3 3 0 000-6z',
    items: [
      { to: '/admin/routing-logs', label: t('admin.adminLayout.menu.routingLogs'), permission: 'routing_log:read' },
      { to: '/admin/routing-quality', label: t('admin.adminLayout.menu.routingQuality'), permission: 'routing_quality:read' },
      { to: '/admin/audit-logs', label: t('admin.adminLayout.menu.auditLogs'), permission: 'audit_log:read' },
    ],
  },
  {
    title: t('admin.adminLayout.menu.orchestrationControl'),
    icon: 'M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83',
    items: [
      { to: '/admin/orchestration-flags', label: t('admin.adminLayout.menu.orchestrationFlags'), permission: 'orchestration_flag:read' },
    ],
  },
  {
    title: t('admin.adminLayout.menu.billingOps'),
    icon: 'M2 5h20v14H2zM2 10h20M6 15h4',
    items: [
      { to: '/admin/billing', label: t('admin.adminLayout.menu.billing'), permissions: ['plan:read', 'redeem_code:read'] },
      { to: '/admin/cost-stats', label: t('admin.adminLayout.menu.costStats'), permissions: ['cost_stats:read'] },
      { to: '/admin/cost-strategy', label: t('admin.adminLayout.menu.costStrategy'), permission: 'model_pool:read' },
    ],
  },
  {
    title: t('admin.adminLayout.menu.showcase'),
    icon: 'M12 2l3 7h7l-5.5 4 2 7-6.5-4-6.5 4 2-7L2 9h7z',
    items: [
      { to: '/admin/showcase', label: t('admin.adminLayout.menu.showcaseReview'), permission: 'showcase:read' },
    ],
  },
  {
    title: 'OpenAPI',
    icon: 'M8 6l-6 6 6 6M16 6l6 6-6 6',
    items: [
      { to: '/admin/openapi', label: t('admin.adminLayout.menu.openapi'), permission: 'openapi:read' },
    ],
  },
] as MenuGroup[]).map(group => ({
  ...group,
  items: group.items.filter((item) => (item.permissions ? adminStore.hasAllPermissions(item.permissions) : adminStore.hasPermission(item.permission || ''))),
})).filter(group => group.items.length > 0))

const adminDisplayName = computed(() => adminStore.admin.name || adminStore.admin.username || adminStore.admin.email || 'Admin')
const adminSubTitle = computed(() => adminStore.admin.username || adminStore.admin.email || t('admin.adminLayout.superAdmin'))

const resetPasswordForm = () => {
  passwordForm.value = { currentPassword: '', newPassword: '', confirmPassword: '' }
}

const handleChangePassword = async () => {
  if (!passwordForm.value.currentPassword || !passwordForm.value.newPassword) {
    Message.error(t('admin.adminLayout.enterPasswordPrompt'))
    return
  }
  if (passwordForm.value.newPassword !== passwordForm.value.confirmPassword) {
    Message.error(t('admin.adminLayout.passwordMismatch'))
    return
  }
  try {
    passwordLoading.value = true
    await adminChangePassword(passwordForm.value.currentPassword, passwordForm.value.newPassword)
    Message.success(t('admin.adminLayout.passwordChanged'))
    passwordModalVisible.value = false
    resetPasswordForm()
    await adminLogout()
    await router.replace('/admin/login')
  } finally {
    passwordLoading.value = false
  }
}

const handleLogout = async () => {
  await adminLogout()
  await router.replace('/admin/login')
}
</script>

<template>
  <section class="admin-layout" :class="{ collapsed }">
    <aside class="admin-sidebar">
      <div class="sidebar-header">
        <router-link class="admin-brand" to="/admin">
          <span class="brand-mark">OA</span>
          <span class="brand-text">OpenAgent Admin</span>
        </router-link>
        <button class="collapse-btn" :title="collapsed ? t('admin.adminLayout.expandSidebar') : t('admin.adminLayout.collapseSidebar')" @click="toggleSidebar">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
      </div>
      <nav class="admin-menu">
        <div v-for="group in menuGroups" :key="group.title" class="menu-group">
          <!-- 展开状态：可点击的分组头部 -->
          <a-tooltip
            v-if="collapsed"
            :content="group.title"
            position="right"
            :mini="true"
          >
            <div class="group-icon-only">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path :d="group.icon" />
              </svg>
            </div>
          </a-tooltip>
          <!-- 收起状态不显示子项 -->
          <template v-if="!collapsed">
            <div class="group-header" @click="toggleGroup(group.title)">
              <svg class="group-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path :d="group.icon" />
              </svg>
              <span class="group-title-text">{{ group.title }}</span>
              <svg class="group-arrow" :class="{ rotated: !isGroupExpanded(group.title) }" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M6 9l6 6 6-6" />
              </svg>
            </div>
            <div v-show="isGroupExpanded(group.title)" class="group-items">
              <router-link v-for="item in group.items" :key="item.to" :to="item.to" class="menu-item">
                {{ item.label }}
              </router-link>
            </div>
          </template>
        </div>
      </nav>
    </aside>
    <main class="admin-main">
      <header class="admin-topbar">
        <div>
          <p class="topbar-kicker">Management Console</p>
          <h1>{{ t('admin.adminLayout.adminConsole') }}</h1>
        </div>
        <div class="admin-account">
          <div class="admin-avatar">{{ adminDisplayName.slice(0, 1) || 'A' }}</div>
          <div>
            <strong>{{ adminDisplayName }}</strong>
            <p>{{ adminSubTitle }}</p>
          </div>
          <a-button type="outline" @click="passwordModalVisible = true">{{ t('admin.adminLayout.changePassword') }}</a-button>
          <a-button type="outline" @click="handleLogout">{{ t('admin.adminLayout.logout') }}</a-button>
        </div>
      </header>
      <section class="admin-content" :class="{ 'admin-content--fluid': isFluidRoute }">
        <router-view />
      </section>
    </main>
    <a-modal v-model:visible="passwordModalVisible" :title="t('admin.adminLayout.changePassword')" :confirm-loading="passwordLoading" @ok="handleChangePassword" @cancel="resetPasswordForm">
      <a-form :model="passwordForm" layout="vertical">
        <a-form-item :label="t('admin.adminLayout.currentPassword')">
          <a-input-password v-model="passwordForm.currentPassword" :placeholder="t('admin.adminLayout.currentPasswordPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('admin.adminLayout.newPassword')">
          <a-input-password v-model="passwordForm.newPassword" :placeholder="t('admin.adminLayout.newPasswordPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('admin.adminLayout.confirmPassword')">
          <a-input-password v-model="passwordForm.confirmPassword" :placeholder="t('admin.adminLayout.confirmPasswordPlaceholder')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>

<style scoped>
.admin-layout {
  height: 100vh;
  display: grid;
  grid-template-columns: 252px 1fr;
  background: #f4f7fb;
  color: #172033;
  transition: grid-template-columns 0.25s ease;
  overflow: hidden;
}

.admin-layout.collapsed {
  grid-template-columns: 72px 1fr;
}

.admin-sidebar {
  display: flex;
  flex-direction: column;
  background: #0b1220;
  color: #f5f8ff;
  overflow: hidden;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 20px 16px;
  gap: 8px;
}

.collapsed .sidebar-header {
  flex-direction: column;
  padding: 20px 0 16px;
}

.admin-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  color: inherit;
  font-weight: 800;
  text-decoration: none;
  overflow: hidden;
}

.brand-mark {
  display: inline-flex;
  width: 38px;
  height: 38px;
  min-width: 38px;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: linear-gradient(135deg, #5f8cff, #8f6dff);
  font-size: 12px;
  letter-spacing: 0.08em;
}

.brand-text {
  white-space: nowrap;
  transition: opacity 0.2s ease;
}

.collapsed .brand-text {
  opacity: 0;
  width: 0;
}

.collapse-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  min-width: 28px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 8px;
  background: transparent;
  color: #7a8aa4;
  cursor: pointer;
  transition: all 0.2s ease;
}

.collapse-btn:hover {
  border-color: rgba(95, 140, 255, 0.5);
  color: #fff;
  background: rgba(95, 140, 255, 0.1);
}

.collapsed .collapse-btn svg {
  transform: rotate(180deg);
}

.collapse-btn svg {
  transition: transform 0.25s ease;
}

.admin-menu {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px 12px 24px;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.15) transparent;
}

.admin-menu::-webkit-scrollbar {
  width: 6px;
}

.admin-menu::-webkit-scrollbar-track {
  background: transparent;
}

.admin-menu::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.12);
}

.admin-menu::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.25);
}

.menu-group {
  margin-bottom: 4px;
}

.menu-group:last-child {
  margin-bottom: 0;
}

.group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 12px;
  color: #8f9db5;
  cursor: pointer;
  user-select: none;
  transition: color 0.15s ease, background 0.15s ease;
}

.group-header:hover {
  color: #c9d5e8;
  background: rgba(255, 255, 255, 0.04);
}

.group-icon {
  flex-shrink: 0;
  opacity: 0.7;
}

.group-title-text {
  flex: 1;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  white-space: nowrap;
  overflow: hidden;
  text-transform: uppercase;
}

.group-arrow {
  flex-shrink: 0;
  opacity: 0.4;
  transition: transform 0.2s ease;
}

.group-arrow.rotated {
  transform: rotate(-90deg);
}

.group-items {
  display: grid;
  gap: 2px;
  margin-top: 2px;
  padding-left: 24px;
}

.menu-item {
  display: flex;
  align-items: center;
  padding: 9px 14px;
  border-radius: 10px;
  color: #b9c7dd;
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  font-size: 13px;
  transition: color 0.15s ease, background 0.15s ease;
}

.menu-item.router-link-active,
.menu-item:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.1);
}

.menu-item.router-link-active {
  font-weight: 600;
}

.group-icon-only {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  margin: 0 auto 8px;
  border-radius: 12px;
  color: #8f9db5;
  cursor: default;
  transition: color 0.15s ease, background 0.15s ease;
}

.group-icon-only:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.08);
}

.admin-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.admin-topbar {
  min-height: 86px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 22px 32px;
  border-bottom: 1px solid #e1e8f2;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(12px);
  flex-shrink: 0;
}

.topbar-kicker {
  margin: 0 0 4px;
  color: #6b7a90;
  font-size: 12px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: 24px;
  letter-spacing: -0.04em;
}

.admin-account {
  display: flex;
  align-items: center;
  gap: 12px;
}

.admin-account p {
  margin: 2px 0 0;
  color: #6b7a90;
  font-size: 12px;
}

.admin-avatar {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 999px;
  background: #172033;
  color: #fff;
  font-weight: 800;
}

.admin-content {
  padding: 28px 32px 56px;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

/*
  约束所有页面根元素的最小宽度，防止宽内容（长表格、长按钮行）撑开
  导致按钮被挤出屏幕；同时 flex-direction: column 让交叉轴 stretch
  使空内容页面也能填满容器宽度，避免按钮缩成一团。
*/
.admin-content > * {
  min-width: 0;
  width: 100%;
  flex-shrink: 0;
}

/* fluid 模式：编辑器画布路由取消 padding，让画布填满 topbar 下方区域 */
.admin-content--fluid {
  padding: 0;
  overflow: hidden;
}
</style>
