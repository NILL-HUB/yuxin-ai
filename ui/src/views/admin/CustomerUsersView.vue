<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message, Modal } from '@arco-design/web-vue'
import {
  disableCustomerUser,
  enableCustomerUser,
  listCustomerUsers,
  revokeCustomerUserSessions,
  setCustomerUserSuperior,
} from '@/services/admin-customer-users'
import { assignAppsToUser, listUserAppAssignments, revokeUserAppAssignment } from '@/services/admin-app-assignments'
import { listAdminApps, type AdminAppRecord } from '@/services/admin-apps'
import { type AppAssignment } from '@/models/app-assignment'
import { getErrorMessage } from '@/utils/error'
import { type CustomerUser } from '@/models/admin-customer-user'
import { useAdminStore } from '@/stores/admin'

const { t } = useI18n()
const adminStore = useAdminStore()
const canManageDistribution = computed(() => adminStore.hasPermission('distribution:manage'))

const loading = ref(false)
const actionLoading = ref(false)
const users = ref<CustomerUser[]>([])
const total = ref(0)
const filters = ref({ keyword: '', status: '' as '' | 'active' | 'disabled', current_page: 1, page_size: 20 })

// 应用分配弹窗
const selectedAssignmentUser = ref<CustomerUser | null>(null)
const assignments = ref<AppAssignment[]>([])
const assignmentAppIds = ref<string[]>([])
const availableApps = ref<AdminAppRecord[]>([])

// 上级绑定抽屉
const selectedSuperiorUser = ref<CustomerUser | null>(null)
const superiorInviterId = ref('')
const superiorLoading = ref(false)
const superiorOptions = ref<{ label: string; value: string }[]>([])

const statusOptions = computed(() => [
  { label: t('admin.customerUsers.allStatus'), value: '' },
  { label: t('admin.customerUsers.statusActive'), value: 'active' },
  { label: t('admin.customerUsers.statusDisabled'), value: 'disabled' },
])

const activeCount = computed(() => users.value.filter((user) => user.status === 'active').length)

const formatTime = (value: number | null) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const columns = computed(() => [
  { title: t('admin.customerUsers.user'), slotName: 'user' },
  { title: t('admin.customerUsers.superiorCol'), slotName: 'superior' },
  { title: t('admin.customerUsers.status'), slotName: 'status' },
  { title: t('admin.customerUsers.onlineStatus'), slotName: 'online_status' },
  { title: t('admin.customerUsers.lastLogin'), slotName: 'last_login' },
  { title: t('admin.customerUsers.actions'), slotName: 'actions', width: 360 },
])

const appOptions = computed(() =>
  availableApps.value.map((app) => ({ label: app.name, value: app.id })),
)

const loadUsers = async () => {
  loading.value = true
  try {
    const response = await listCustomerUsers(filters.value)
    users.value = response.list
    total.value = response.paginator.total_record
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.customerUsers.loadFailed')))
  } finally {
    loading.value = false
  }
}

const loadAvailableApps = async () => {
  try {
    const data = await listAdminApps({ current_page: 1, page_size: 100, status: 'all' })
    availableApps.value = data.list || []
  } catch {
    availableApps.value = []
  }
}

const handleSearch = async () => {
  filters.value.current_page = 1
  await loadUsers()
}

const onPageChange = async (page: number) => {
  filters.value.current_page = page
  await loadUsers()
}

const onPageSizeChange = async (size: number) => {
  filters.value.page_size = size
  filters.value.current_page = 1
  await loadUsers()
}

const handleDisable = async (user: CustomerUser) => {
  actionLoading.value = true
  try {
    await disableCustomerUser(user.id, t('admin.customerUsers.disableReason'))
    Message.success(t('admin.customerUsers.userDisabled'))
    await loadUsers()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.customerUsers.disableFailed')))
  } finally {
    actionLoading.value = false
  }
}

const handleEnable = async (user: CustomerUser) => {
  actionLoading.value = true
  try {
    await enableCustomerUser(user.id)
    Message.success(t('admin.customerUsers.userEnabled'))
    await loadUsers()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.customerUsers.enableFailed')))
  } finally {
    actionLoading.value = false
  }
}

const handleRevokeSessions = async (user: CustomerUser) => {
  actionLoading.value = true
  try {
    const response = await revokeCustomerUserSessions(user.id)
    Message.success(t('admin.customerUsers.sessionsRevoked', { count: response.revoked_sessions }))
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.customerUsers.revokeSessionsFailed')))
  } finally {
    actionLoading.value = false
  }
}

const openAssignments = async (user: CustomerUser) => {
  selectedAssignmentUser.value = user
  assignmentAppIds.value = []
  actionLoading.value = true
  try {
    const response = await listUserAppAssignments(user.id)
    assignments.value = response.list
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.customerUsers.loadAssignmentsFailed')))
  } finally {
    actionLoading.value = false
  }
}

const closeAssignments = () => {
  selectedAssignmentUser.value = null
  assignments.value = []
  assignmentAppIds.value = []
}

const handleAssignApps = async () => {
  if (!selectedAssignmentUser.value || assignmentAppIds.value.length === 0) return
  actionLoading.value = true
  try {
    await assignAppsToUser(selectedAssignmentUser.value.id, assignmentAppIds.value)
    assignmentAppIds.value = []
    Message.success(t('admin.customerUsers.appAssigned'))
    const response = await listUserAppAssignments(selectedAssignmentUser.value.id)
    assignments.value = response.list
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.customerUsers.assignFailed')))
  } finally {
    actionLoading.value = false
  }
}

const handleRevokeAssignment = async (assignment: AppAssignment) => {
  if (!selectedAssignmentUser.value) return
  actionLoading.value = true
  try {
    await revokeUserAppAssignment(selectedAssignmentUser.value.id, assignment.id)
    Message.success(t('admin.customerUsers.assignmentRevoked'))
    const response = await listUserAppAssignments(selectedAssignmentUser.value.id)
    assignments.value = response.list
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.customerUsers.revokeAssignmentFailed')))
  } finally {
    actionLoading.value = false
  }
}

const openSuperior = (user: CustomerUser) => {
  selectedSuperiorUser.value = user
  superiorInviterId.value = ''
  superiorOptions.value = [
    {
      label: `${user.name || user.email || user.id}${user.email && user.name ? ` · ${user.email}` : ''}`,
      value: user.id,
    },
  ]
}

const onSuperiorSearch = async (keyword: string) => {
  try {
    const response = await listCustomerUsers({ keyword, status: '', current_page: 1, page_size: 20 })
    superiorOptions.value = (response.list || []).map((user) => ({
      label: `${user.name || user.email || user.id}${user.email && user.name ? ` · ${user.email}` : ''}`,
      value: user.id,
    }))
  } catch {
    superiorOptions.value = []
  }
}

const copyUserId = async (id: string) => {
  try {
    await navigator.clipboard.writeText(id)
    Message.success(t('admin.customerUsers.idCopied'))
  } catch {
    Message.error(t('admin.customerUsers.copyFailed'))
  }
}

const closeSuperior = () => {
  selectedSuperiorUser.value = null
  superiorInviterId.value = ''
}

const superiorOptionLabel = (id: string) => {
  const option = superiorOptions.value.find((item) => item.value === id)
  return option?.label || id
}

const doBindSuperior = async (user: CustomerUser, inviterId: string) => {
  superiorLoading.value = true
  try {
    await setCustomerUserSuperior(user.id, inviterId)
    Message.success(t('admin.customerUsers.superiorBound'))
    closeSuperior()
    await loadUsers()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.customerUsers.superiorBindFailed')))
  } finally {
    superiorLoading.value = false
  }
}

const handleBindSuperior = async () => {
  if (!selectedSuperiorUser.value) return
  const inviterId = superiorInviterId.value.trim()
  if (!inviterId) {
    Message.error(t('admin.customerUsers.superiorInviterRequired'))
    return
  }
  const user = selectedSuperiorUser.value
  const newName = superiorOptionLabel(inviterId)
  if (user.superior_id) {
    Modal.confirm({
      title: t('admin.customerUsers.replaceSuperiorTitle'),
      content: t('admin.customerUsers.replaceSuperiorDesc', {
        old: user.superior_name || user.superior_email || t('admin.customerUsers.noSuperiorText'),
        name: newName,
      }),
      okText: t('admin.customerUsers.superiorBind'),
      cancelText: t('common.actions.cancel'),
      onOk: () => doBindSuperior(user, inviterId),
    })
  } else {
    await doBindSuperior(user, inviterId)
  }
}

const doUnbindSuperior = async (user: CustomerUser) => {
  superiorLoading.value = true
  try {
    const result = await setCustomerUserSuperior(user.id, null)
    if (result?.unbound) {
      Message.success(t('admin.customerUsers.superiorUnbound'))
    } else {
      Message.success(t('admin.customerUsers.superiorUnbound'))
    }
    closeSuperior()
    await loadUsers()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.customerUsers.superiorUnbindFailed')))
  } finally {
    superiorLoading.value = false
  }
}

const handleUnbindSuperior = async () => {
  if (!selectedSuperiorUser.value) return
  const user = selectedSuperiorUser.value
  if (user.superior_id) {
    Modal.confirm({
      title: t('admin.customerUsers.unbindSuperiorTitle'),
      content: t('admin.customerUsers.unbindSuperiorDesc', {
        name: user.superior_name || user.superior_email || t('admin.customerUsers.noSuperiorText'),
      }),
      okText: t('admin.customerUsers.superiorUnbind'),
      cancelText: t('common.actions.cancel'),
      onOk: () => doUnbindSuperior(user),
    })
  } else {
    await doUnbindSuperior(user)
  }
}

onMounted(async () => {
  await loadUsers()
  await loadAvailableApps()
})
</script>

<template>
  <section class="space-y-6 p-6">
    <!-- 页头 -->
    <header class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-semibold text-gray-900">{{ t('admin.customerUsers.title') }}</h1>
        <p class="mt-1 text-sm text-gray-500">{{ t('admin.customerUsers.description') }}</p>
      </div>
      <div class="flex items-center gap-2 rounded-lg border bg-white px-4 py-2">
        <span class="text-sm text-gray-500">{{ t('admin.customerUsers.activeUsersLabel') }}</span>
        <span class="text-xl font-semibold text-green-600">{{ activeCount }}</span>
      </div>
    </header>

    <!-- 筛选 -->
    <div class="rounded-lg border bg-white p-4">
      <div class="grid gap-3 md:grid-cols-4">
        <a-input v-model="filters.keyword" :placeholder="t('admin.customerUsers.searchPlaceholder')" allow-clear @press-enter="handleSearch" />
        <a-select v-model="filters.status" :options="statusOptions" />
        <a-button type="primary" :loading="loading" @click="handleSearch">{{ t('admin.customerUsers.search') }}</a-button>
      </div>
    </div>

    <!-- 用户表格 -->
    <a-table
      :loading="loading"
      :data="users"
      :columns="columns"
      :pagination="false"
      :bordered="{ wrapper: true, cell: true }"
      row-key="id"
    >
      <template #columns>
        <a-table-column v-for="col of columns" :key="col.slotName" :title="col.title" :width="col.width">
          <template #cell="{ record }">
            <template v-if="col.slotName === 'user'">
              <div class="flex items-start gap-2">
                <a-avatar :size="32">{{ (record.name || record.email || '?').charAt(0).toUpperCase() }}</a-avatar>
                <div class="cell-stack">
                  <span class="font-medium text-gray-900">{{ record.name || '-' }}</span>
                  <span v-if="record.email" class="cell-sub">{{ record.email }}</span>
                  <div class="cell-id-row">
                    <code class="cell-id">{{ record.id }}</code>
                    <a-button size="mini" type="text" @click="copyUserId(record.id)">{{ t('admin.customerUsers.copyId') }}</a-button>
                  </div>
                </div>
              </div>
            </template>
            <template v-if="col.slotName === 'superior'">
              <template v-if="record.superior_id">
                <div class="cell-stack">
                  <span>{{ record.superior_name || record.superior_email || '-' }}</span>
                  <span v-if="record.superior_email && record.superior_name" class="cell-sub">{{ record.superior_email }}</span>
                  <div class="cell-id-row">
                    <code class="cell-id">{{ record.superior_id }}</code>
                    <a-button size="mini" type="text" @click="record.superior_id && copyUserId(record.superior_id)">{{ t('admin.customerUsers.copyId') }}</a-button>
                  </div>
                </div>
              </template>
              <span v-else class="text-gray-400">-</span>
            </template>
            <template v-else-if="col.slotName === 'status'">
              <a-tag v-if="record.status === 'active'" size="small" color="green">{{ t('admin.customerUsers.pillActive') }}</a-tag>
              <a-tag v-else size="small" color="red">{{ t('admin.customerUsers.pillDisabled') }}</a-tag>
              <div v-if="record.disabled_reason" class="text-xs text-gray-400 mt-1">{{ record.disabled_reason }}</div>
            </template>
            <template v-else-if="col.slotName === 'online_status'">
              <a-tag v-if="record.is_online" size="small" color="green">{{ t('admin.customerUsers.online') }}</a-tag>
              <a-tag v-else size="small" color="gray">{{ t('admin.customerUsers.offline') }}</a-tag>
            </template>
            <template v-else-if="col.slotName === 'last_login'">
              <div>{{ formatTime(record.last_login_at) }}</div>
              <div v-if="record.last_login_ip" class="text-xs text-gray-400">{{ record.last_login_ip }}</div>
            </template>
            <template v-else-if="col.slotName === 'actions'">
              <a-space wrap>
                <a-button
                  v-if="record.status === 'active'"
                  size="mini"
                  status="danger"
                  :loading="actionLoading"
                  @click="handleDisable(record)"
                >{{ t('admin.customerUsers.disable') }}</a-button>
                <a-button
                  v-else
                  size="mini"
                  type="primary"
                  :loading="actionLoading"
                  @click="handleEnable(record)"
                >{{ t('admin.customerUsers.enable') }}</a-button>
                <a-button
                  v-if="record.is_online"
                  size="mini"
                  status="warning"
                  :loading="actionLoading"
                  @click="handleRevokeSessions(record)"
                >{{ t('admin.customerUsers.revokeSessions') }}</a-button>
                <a-button size="mini" type="primary" :loading="actionLoading" @click="openAssignments(record)">{{ t('admin.customerUsers.assignApp') }}</a-button>
                <a-button v-if="canManageDistribution" size="mini" :loading="actionLoading" @click="openSuperior(record)">{{ t('admin.customerUsers.superior') }}</a-button>
              </a-space>
            </template>
          </template>
        </a-table-column>
      </template>
    </a-table>

    <!-- 分页 -->
    <div class="flex justify-end">
      <a-pagination
        :total="total"
        :current="filters.current_page"
        :page-size="filters.page_size"
        show-total
        show-page-size
        :page-size-options="[10, 20, 50]"
        @change="onPageChange"
        @page-size-change="onPageSizeChange"
      />
    </div>

    <!-- 应用分配抽屉 -->
    <a-drawer
      :visible="!!selectedAssignmentUser"
      :width="560"
      :title="t('admin.customerUsers.assignTitle', { name: selectedAssignmentUser?.name || selectedAssignmentUser?.email || '' })"
      @cancel="closeAssignments"
    >
      <div class="space-y-4">
        <!-- 分配新应用 -->
        <div class="rounded-lg border bg-gray-50 p-4">
          <div class="text-sm font-medium text-gray-700 mb-2">{{ t('admin.customerUsers.assignDesc') }}</div>
          <div class="flex gap-2">
            <a-select
              v-model="assignmentAppIds"
              :options="appOptions"
              multiple
              allow-search
              :placeholder="t('admin.customerUsers.appSelectPlaceholder')"
              class="flex-1"
            />
            <a-button type="primary" :loading="actionLoading" :disabled="assignmentAppIds.length === 0" @click="handleAssignApps">{{ t('admin.customerUsers.confirmAssign') }}</a-button>
          </div>
        </div>

        <!-- 已分配列表 -->
        <div class="space-y-2">
          <div class="text-sm font-medium text-gray-700">{{ t('admin.customerUsers.assignedApps') }}</div>
          <div v-if="assignments.length === 0" class="text-sm text-gray-400 py-4 text-center">{{ t('admin.customerUsers.noAssignments') }}</div>
          <div
            v-for="assignment in assignments"
            :key="assignment.id"
            class="flex items-center justify-between rounded-lg border bg-white p-3"
          >
            <div class="flex items-center gap-3 min-w-0">
              <a-avatar :size="32" shape="square">{{ (assignment.app?.name || assignment.app_id || '?').charAt(0).toUpperCase() }}</a-avatar>
              <div class="flex flex-col min-w-0">
                <span class="font-medium text-gray-900 truncate">{{ assignment.app?.name || assignment.app_id }}</span>
                <span class="text-xs text-gray-500">
                  {{ assignment.status === 'active' ? t('admin.customerUsers.assigned') : t('admin.customerUsers.revoked') }}
                  · {{ formatTime(assignment.assigned_at) }}
                </span>
              </div>
            </div>
            <a-button
              v-if="assignment.status === 'active'"
              size="mini"
              status="danger"
              :loading="actionLoading"
              @click="handleRevokeAssignment(assignment)"
            >{{ t('admin.customerUsers.revoke') }}</a-button>
          </div>
        </div>
      </div>
    </a-drawer>

    <!-- 上级绑定抽屉 -->
    <a-drawer
      :visible="!!selectedSuperiorUser"
      :width="520"
      :title="t('admin.customerUsers.superiorTitle', { name: selectedSuperiorUser?.name || selectedSuperiorUser?.email || '' })"
      @cancel="closeSuperior"
    >
      <div class="space-y-4">
        <div class="rounded-lg border bg-gray-50 p-4">
          <div class="text-sm font-medium text-gray-700 mb-2">{{ t('admin.customerUsers.superiorDesc') }}</div>
          <div v-if="selectedSuperiorUser?.superior_id" class="rounded-lg border border-amber-200 bg-amber-50 p-3 mb-3">
            <div class="text-xs text-amber-700 font-medium mb-1">{{ t('admin.customerUsers.currentSuperior') }}</div>
            <div class="text-sm text-gray-800">
              {{ selectedSuperiorUser.superior_name || selectedSuperiorUser.superior_email || '-' }}
              <span v-if="selectedSuperiorUser.superior_email && selectedSuperiorUser.superior_name" class="text-gray-500"> · {{ selectedSuperiorUser.superior_email }}</span>
            </div>
            <code class="text-xs text-gray-400">{{ selectedSuperiorUser.superior_id }}</code>
          </div>
          <div class="flex gap-2">
            <a-select
              v-model="superiorInviterId"
              :options="superiorOptions"
              allow-search
              allow-clear
              :filter-option="false"
              :placeholder="t('admin.customerUsers.superiorSelectPlaceholder')"
              class="flex-1"
              @search="onSuperiorSearch"
            />
          </div>
          <div class="mt-3 flex gap-2">
            <a-button type="primary" :loading="superiorLoading" @click="handleBindSuperior">{{ t('admin.customerUsers.superiorBind') }}</a-button>
            <a-button status="warning" :loading="superiorLoading" @click="handleUnbindSuperior">{{ t('admin.customerUsers.superiorUnbind') }}</a-button>
          </div>
        </div>
      </div>
    </a-drawer>
  </section>
</template>

<style scoped>
.cell-stack {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.cell-sub {
  color: #667085;
  font-size: 12px;
}

.cell-id-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.cell-id {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 11px;
  color: #98a2b3;
}
</style>