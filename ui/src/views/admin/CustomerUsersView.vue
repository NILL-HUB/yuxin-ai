<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import {
  disableCustomerUser,
  enableCustomerUser,
  listCustomerUsers,
  revokeCustomerUserSessions,
} from '@/services/admin-customer-users'
import { assignAppsToUser, listUserAppAssignments, revokeUserAppAssignment } from '@/services/admin-app-assignments'
import { listAdminApps, type AdminAppRecord } from '@/services/admin-apps'
import { type AppAssignment } from '@/models/app-assignment'
import { getErrorMessage } from '@/utils/error'
import { type CustomerUser } from '@/models/admin-customer-user'

const { t } = useI18n()

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
  { title: t('admin.customerUsers.status'), slotName: 'status' },
  { title: t('admin.customerUsers.onlineStatus'), slotName: 'online_status' },
  { title: t('admin.customerUsers.lastLogin'), slotName: 'last_login' },
  { title: t('admin.customerUsers.actions'), slotName: 'actions', width: 280 },
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
              <div class="flex items-center gap-2">
                <a-avatar :size="32">{{ (record.name || record.email || '?').charAt(0).toUpperCase() }}</a-avatar>
                <div class="flex flex-col">
                  <span class="font-medium text-gray-900">{{ record.name || '-' }}</span>
                  <span class="text-xs text-gray-500">{{ record.email }}</span>
                </div>
              </div>
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
  </section>
</template>