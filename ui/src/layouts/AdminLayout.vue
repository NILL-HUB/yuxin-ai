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
}

const menuItems = computed(() =>
  ([
    { to: '/admin/apps', label: '应用管理', permission: 'app:read' },
    { to: '/admin/workflows', label: '工作流管理', permission: 'workflow:read' },
    { to: '/admin/datasets', label: '知识库', permission: 'dataset:read' },
    { to: '/admin/tools', label: '工具管理', permission: 'tool:read' },
    { to: '/admin/mcp', label: 'MCP 管理', permission: 'mcp:read' },
    { to: '/admin/skills', label: 'Skills 管理', permission: 'skill:read' },
    { to: '/admin/users', label: '用户管理', permission: 'user:read' },
    { to: '/admin/billing', label: '套餐卡密', permissions: ['plan:read', 'redeem_code:read'] },
    { to: '/admin/admin-users', label: '管理员', permission: 'admin_user:read' },
    { to: '/admin/roles', label: '角色权限', permission: 'role:read' },
    { to: '/admin/audit-logs', label: '审计日志', permission: 'audit_log:read' },
  ] as MenuItem[]).filter((item) => (item.permissions ? adminStore.hasAllPermissions(item.permissions) : adminStore.hasPermission(item.permission || ''))),
)

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
        <router-link v-for="item in menuItems" :key="item.to" :to="item.to">{{ item.label }}</router-link>
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
