<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { adminChangePassword, adminLogout } from '@/services/admin-auth'
import { useAdminStore } from '@/stores/admin'

const router = useRouter()
const adminStore = useAdminStore()
const passwordModalVisible = ref(false)
const passwordLoading = ref(false)
const passwordForm = ref({ currentPassword: '', newPassword: '', confirmPassword: '' })

type MenuItem = {
  to: string
  label: string
  permission?: string
  permissions?: string[]
  roles?: string[]
}

type MenuGroup = {
  title: string
  items: MenuItem[]
}

const menuGroups = computed(() => ([
  {
    title: '概览',
    items: [
      { to: '/admin', label: '仪表盘', permission: 'admin:access' },
    ],
  },
  {
    title: 'RBAC 管理',
    items: [
      { to: '/admin/admin-users', label: '管理员', permission: 'admin_user:read' },
      { to: '/admin/roles', label: '角色权限', permission: 'role:read' },
      { to: '/admin/users', label: '客户用户', permission: 'user:read' },
    ],
  },
  {
    title: '资源编排',
    items: [
      { to: '/admin/apps', label: '应用编排', permission: 'app:read' },
      { to: '/admin/workflows', label: '工作流编排', permission: 'workflow:read' },
      { to: '/admin/datasets', label: '知识库管理', permission: 'dataset:read' },
      { to: '/admin/tools', label: 'API工具', permission: 'tool:read' },
      { to: '/admin/mcp', label: 'MCP管理', permission: 'mcp:read' },
      { to: '/admin/skills', label: 'Skills管理', permission: 'skill:read' },
    ],
  },
  {
    title: '资源运营',
    items: [
      { to: '/admin/store/public-apps', label: '应用商店', permission: 'app:read' },
      { to: '/admin/store/workflows', label: '工作流商店', permission: 'workflow:read' },
      { to: '/admin/store/tools', label: '工具商店', permission: 'tool:read' },
      { to: '/admin/store/skills', label: '技能商店', permission: 'skill:read' },
      { to: '/admin/store/mcp', label: 'MCP商店', permission: 'mcp:read' },
    ],
  },
  {
    title: '池治理',
    items: [
      { to: '/admin/agent-pool', label: 'Agent池配置', permission: 'agent_pool:read' },
      { to: '/admin/tool-governance', label: '工具池治理', permission: 'tool_governance:read' },
      { to: '/admin/models', label: '模型池管理', permission: 'model_pool:read' },
    ],
  },
  {
    title: '观测中心',
    items: [
      { to: '/admin/routing-logs', label: '路由日志', permission: 'routing_log:read' },
      { to: '/admin/routing-quality', label: '路由质量', permission: 'routing_quality:read' },
      { to: '/admin/audit-logs', label: '审计日志', permission: 'audit_log:read' },
    ],
  },
  {
    title: '编排控制',
    items: [
      { to: '/admin/orchestration-flags', label: '功能开关', permission: 'orchestration_flag:read' },
    ],
  },
  {
    title: '计费运营',
    items: [
      { to: '/admin/billing', label: '套餐卡密', permissions: ['plan:read', 'redeem_code:read'] },
    ],
  },
  {
    title: '案例展示',
    items: [
      { to: '/admin/showcase', label: '案例审核', permission: 'showcase:read' },
    ],
  },
  {
    title: 'OpenAPI',
    items: [
      { to: '/admin/openapi', label: 'API管理', permission: 'openapi:read' },
    ],
  },
] as MenuGroup[]).map(group => ({
  ...group,
  items: group.items.filter((item) => (item.permissions ? adminStore.hasAllPermissions(item.permissions) : adminStore.hasPermission(item.permission || ''))),
})).filter(group => group.items.length > 0))

const adminDisplayName = computed(() => adminStore.admin.name || adminStore.admin.username || adminStore.admin.email || 'Admin')
const adminSubTitle = computed(() => adminStore.admin.username || adminStore.admin.email || '超级管理员')

const resetPasswordForm = () => {
  passwordForm.value = { currentPassword: '', newPassword: '', confirmPassword: '' }
}

const handleChangePassword = async () => {
  if (!passwordForm.value.currentPassword || !passwordForm.value.newPassword) {
    Message.error('请输入当前密码和新密码')
    return
  }
  if (passwordForm.value.newPassword !== passwordForm.value.confirmPassword) {
    Message.error('两次输入的新密码不一致')
    return
  }
  try {
    passwordLoading.value = true
    await adminChangePassword(passwordForm.value.currentPassword, passwordForm.value.newPassword)
    Message.success('密码修改成功，请使用新密码重新登录')
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
  <section class="admin-layout">
    <aside class="admin-sidebar">
      <router-link class="admin-brand" to="/admin">
        <span class="brand-mark">OA</span>
        <span>OpenAgent Admin</span>
      </router-link>
      <nav class="admin-menu">
        <div v-for="group in menuGroups" :key="group.title" class="menu-group">
          <div class="menu-group-title">{{ group.title }}</div>
          <router-link v-for="item in group.items" :key="item.to" :to="item.to">{{ item.label }}</router-link>
        </div>
      </nav>
    </aside>
    <main class="admin-main">
      <header class="admin-topbar">
        <div>
          <p class="topbar-kicker">Management Console</p>
          <h1>后台管理</h1>
        </div>
        <div class="admin-account">
          <div class="admin-avatar">{{ adminDisplayName.slice(0, 1) || 'A' }}</div>
          <div>
            <strong>{{ adminDisplayName }}</strong>
            <p>{{ adminSubTitle }}</p>
          </div>
          <a-button type="outline" @click="passwordModalVisible = true">修改密码</a-button>
          <a-button type="outline" @click="handleLogout">退出</a-button>
        </div>
      </header>
      <section class="admin-content">
        <router-view />
      </section>
    </main>
    <a-modal v-model:visible="passwordModalVisible" title="修改密码" :confirm-loading="passwordLoading" @ok="handleChangePassword" @cancel="resetPasswordForm">
      <a-form :model="passwordForm" layout="vertical">
        <a-form-item label="当前密码">
          <a-input-password v-model="passwordForm.currentPassword" placeholder="请输入当前密码" />
        </a-form-item>
        <a-form-item label="新密码">
          <a-input-password v-model="passwordForm.newPassword" placeholder="字母+数字，可含_和.，6-32位" />
        </a-form-item>
        <a-form-item label="确认新密码">
          <a-input-password v-model="passwordForm.confirmPassword" placeholder="请再次输入新密码" />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>

<style scoped>
.admin-layout {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 252px 1fr;
  background: #f4f7fb;
  color: #172033;
}

.admin-sidebar {
  padding: 28px 20px;
  background: #0b1220;
  color: #f5f8ff;
}

.admin-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  color: inherit;
  font-weight: 800;
  text-decoration: none;
}

.brand-mark {
  display: inline-flex;
  width: 38px;
  height: 38px;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: linear-gradient(135deg, #5f8cff, #8f6dff);
  font-size: 12px;
  letter-spacing: 0.08em;
}

.admin-menu {
  display: grid;
  gap: 8px;
  margin-top: 40px;
}

.admin-menu a {
  padding: 12px 14px;
  border-radius: 14px;
  color: #b9c7dd;
  text-decoration: none;
}

.admin-menu a.router-link-active,
.admin-menu a:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.1);
}

.menu-group {
  display: grid;
  gap: 4px;
  margin-bottom: 16px;
}

.menu-group:last-child {
  margin-bottom: 0;
}

.menu-group-title {
  padding: 0 14px;
  margin-bottom: 6px;
  color: #7a8aa4;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.admin-main {
  min-width: 0;
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
}
</style>
