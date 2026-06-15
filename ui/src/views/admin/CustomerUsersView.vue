<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  disableCustomerUser,
  enableCustomerUser,
  listCustomerUsers,
  revokeCustomerUserSessions,
} from '@/services/admin-customer-users'
import { assignAppsToUser, listUserAppAssignments, revokeUserAppAssignment } from '@/services/admin-app-assignments'
import { type AppAssignment } from '@/models/app-assignment'
import { getErrorMessage } from '@/utils/error'
import { type CustomerUser } from '@/models/admin-customer-user'

const loading = ref(false)
const actionLoading = ref(false)
const users = ref<CustomerUser[]>([])
const total = ref(0)
const selectedAssignmentUser = ref<CustomerUser | null>(null)
const assignments = ref<AppAssignment[]>([])
const assignmentAppId = ref('')
const filters = ref({ keyword: '', status: '' as '' | 'active' | 'disabled', current_page: 1, page_size: 20 })

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '正常', value: 'active' },
  { label: '已禁用', value: 'disabled' },
]

const activeCount = computed(() => users.value.filter((user) => user.status === 'active').length)

const formatTime = (value: number | null) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const loadUsers = async () => {
  loading.value = true
  try {
    const response = await listCustomerUsers(filters.value)
    users.value = response.list
    total.value = response.paginator.total_record
  } catch (error) {
    Message.error(getErrorMessage(error, '加载用户失败'))
  } finally {
    loading.value = false
  }
}

const handleSearch = async () => {
  filters.value.current_page = 1
  await loadUsers()
}

const handleDisable = async (user: CustomerUser) => {
  actionLoading.value = true
  try {
    await disableCustomerUser(user.id, '后台管理员禁用')
    Message.success('用户已禁用')
    await loadUsers()
  } catch (error) {
    Message.error(getErrorMessage(error, '禁用用户失败'))
  } finally {
    actionLoading.value = false
  }
}

const handleEnable = async (user: CustomerUser) => {
  actionLoading.value = true
  try {
    await enableCustomerUser(user.id)
    Message.success('用户已解禁')
    await loadUsers()
  } catch (error) {
    Message.error(getErrorMessage(error, '解禁用户失败'))
  } finally {
    actionLoading.value = false
  }
}

const handleRevokeSessions = async (user: CustomerUser) => {
  actionLoading.value = true
  try {
    const response = await revokeCustomerUserSessions(user.id)
    Message.success(`已踢下线 ${response.revoked_sessions} 个会话`)
  } catch (error) {
    Message.error(getErrorMessage(error, '踢下线失败'))
  } finally {
    actionLoading.value = false
  }
}

const openAssignments = async (user: CustomerUser) => {
  selectedAssignmentUser.value = user
  actionLoading.value = true
  try {
    const response = await listUserAppAssignments(user.id)
    assignments.value = response.list
  } catch (error) {
    Message.error(getErrorMessage(error, '加载应用分配失败'))
  } finally {
    actionLoading.value = false
  }
}

const handleAssignApp = async () => {
  if (!selectedAssignmentUser.value || !assignmentAppId.value.trim()) return
  actionLoading.value = true
  try {
    await assignAppsToUser(selectedAssignmentUser.value.id, [assignmentAppId.value.trim()])
    assignmentAppId.value = ''
    Message.success('应用已分配')
    await openAssignments(selectedAssignmentUser.value)
  } catch (error) {
    Message.error(getErrorMessage(error, '分配应用失败'))
  } finally {
    actionLoading.value = false
  }
}

const handleRevokeAssignment = async (assignment: AppAssignment) => {
  if (!selectedAssignmentUser.value) return
  actionLoading.value = true
  try {
    await revokeUserAppAssignment(selectedAssignmentUser.value.id, assignment.id)
    Message.success('应用分配已撤销')
    await openAssignments(selectedAssignmentUser.value)
  } catch (error) {
    Message.error(getErrorMessage(error, '撤销应用分配失败'))
  } finally {
    actionLoading.value = false
  }
}

onMounted(loadUsers)
</script>

<template>
  <section class="customer-users-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Customer Governance</p>
        <h2>用户管理</h2>
        <p>查看客户账号状态，执行禁用、解禁和踢下线操作。</p>
      </div>
      <div class="metric-card">
        <span>当前页正常用户</span>
        <strong>{{ activeCount }}</strong>
      </div>
    </header>

    <section class="toolbar">
      <a-input v-model="filters.keyword" placeholder="搜索邮箱或名称" allow-clear />
      <a-select v-model="filters.status" :options="statusOptions" />
      <a-button type="primary" :loading="loading" @click="handleSearch">查询</a-button>
    </section>

    <section class="users-table" :aria-busy="loading">
      <div class="table-header">
        <span>用户</span>
        <span>状态</span>
        <span>最近登录</span>
        <span>操作</span>
      </div>
      <div v-if="users.length === 0" class="empty-state">暂无用户</div>
      <article v-for="user in users" :key="user.id" class="table-row">
        <div>
          <strong>{{ user.name || user.email }}</strong>
          <p>{{ user.email }}</p>
        </div>
        <div>
          <span class="status-pill" :class="`status-${user.status}`">{{ user.status === 'active' ? '正常' : '已禁用' }}</span>
          <p v-if="user.disabled_reason" class="muted">{{ user.disabled_reason }}</p>
        </div>
        <div>
          <strong>{{ formatTime(user.last_login_at) }}</strong>
          <p>{{ user.last_login_ip || '-' }}</p>
        </div>
        <div class="actions">
          <a-button v-if="user.status === 'active'" size="small" status="danger" :loading="actionLoading" @click="handleDisable(user)">禁用</a-button>
          <a-button v-else size="small" type="primary" :loading="actionLoading" @click="handleEnable(user)">解禁</a-button>
          <a-button size="small" :loading="actionLoading" @click="handleRevokeSessions(user)">踢下线</a-button>
          <a-button size="small" type="primary" :loading="actionLoading" @click="openAssignments(user)">分配应用</a-button>
        </div>
      </article>
    </section>

    <section v-if="selectedAssignmentUser" class="assignment-panel">
      <div>
        <h3>分配应用：{{ selectedAssignmentUser.name || selectedAssignmentUser.email }}</h3>
        <p>输入已发布 App ID，将 AI 功能分配给该客户。</p>
      </div>
      <div class="assignment-form">
        <a-input v-model="assignmentAppId" placeholder="输入 App ID" />
        <a-button type="primary" :loading="actionLoading" @click="handleAssignApp">确认分配</a-button>
      </div>
      <article v-for="assignment in assignments" :key="assignment.id" class="assignment-row">
        <div>
          <strong>{{ assignment.app?.name || assignment.app_id }}</strong>
          <p>{{ assignment.status === 'active' ? '已分配' : '已撤销' }}</p>
        </div>
        <a-button v-if="assignment.status === 'active'" size="small" status="danger" :loading="actionLoading" @click="handleRevokeAssignment(assignment)">撤销</a-button>
      </article>
    </section>

    <footer class="table-footer">共 {{ total }} 个用户</footer>
  </section>
</template>

<style scoped>
.customer-users-page {
  display: grid;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 28px;
  border-radius: 24px;
  background: linear-gradient(135deg, #101828, #263a5f);
  color: #fff;
}

.page-kicker {
  margin: 0 0 8px;
  color: #9fc0ff;
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

h2 {
  margin: 0 0 8px;
  font-size: 30px;
}

.page-header p {
  margin: 0;
  color: #cbd8ec;
}

.metric-card {
  min-width: 160px;
  display: grid;
  align-content: center;
  gap: 8px;
  padding: 20px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.12);
}

.metric-card span {
  color: #dbe7ff;
  font-size: 13px;
}

.metric-card strong {
  font-size: 34px;
}

.toolbar {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) 180px auto;
  gap: 12px;
  padding: 18px;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 14px 40px rgba(15, 23, 42, 0.06);
}

.users-table {
  overflow: hidden;
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 14px 40px rgba(15, 23, 42, 0.06);
}

.table-header,
.table-row {
  display: grid;
  grid-template-columns: 1.3fr 0.8fr 1fr 280px;
  gap: 16px;
  align-items: center;
  padding: 18px 22px;
}

.table-header {
  color: #667085;
  font-size: 13px;
  font-weight: 700;
  background: #f8fafc;
}

.table-row {
  border-top: 1px solid #edf2f7;
}

.table-row p,
.muted {
  margin: 4px 0 0;
  color: #667085;
  font-size: 13px;
}

.status-pill {
  display: inline-flex;
  padding: 5px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.status-active {
  color: #047857;
  background: #d1fae5;
}

.status-disabled {
  color: #b42318;
  background: #fee4e2;
}

.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.assignment-panel {
  display: grid;
  gap: 14px;
  padding: 22px;
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 14px 40px rgba(15, 23, 42, 0.06);
}

.assignment-panel h3,
.assignment-panel p {
  margin: 0;
}

.assignment-panel p,
.assignment-row p {
  margin-top: 4px;
  color: #667085;
  font-size: 13px;
}

.assignment-form {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) auto;
  gap: 10px;
}

.assignment-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding-top: 12px;
  border-top: 1px solid #edf2f7;
}

.empty-state,
.table-footer {
  padding: 24px;
  color: #667085;
  text-align: center;
}
</style>
