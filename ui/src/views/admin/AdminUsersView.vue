<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  createAdminUser,
  disableAdminUser,
  enableAdminUser,
  listAdminUsers,
  resetAdminUserPassword,
  revokeAdminUserSessions,
  updateAdminUser,
  type AdminUser,
} from '@/services/admin-admin-users'
import { listRoles, type Role } from '@/services/admin-roles'
import { getErrorMessage } from '@/utils/error'
import { useAdminStore } from '@/stores/admin'

const { t } = useI18n()
const adminStore = useAdminStore()
const canManageAdmin = computed(() => adminStore.hasPermission('admin_user:disable'))
const canUpdateAdmin = computed(() => adminStore.hasPermission('admin_user:update'))

const loading = ref(false)
const actionLoading = ref(false)
const admins = ref<AdminUser[]>([])
const roles = ref<Role[]>([])
const total = ref(0)

const filters = ref({
  search: '',
  status: 'all',
  current_page: 1,
  page_size: 20,
})

const statusOptions = computed(() => [
  { label: t('admin.adminUsers.allStatus'), value: 'all' },
  { label: t('admin.adminUsers.statusActive'), value: 'active' },
  { label: t('admin.adminUsers.statusDisabled'), value: 'disabled' },
  { label: t('admin.adminUsers.statusPending'), value: 'pending' },
])

// 编辑/新建表单弹窗
const modalVisible = ref(false)
const editMode = ref(false)
const editingId = ref('')
const form = ref({
  username: '',
  email: '',
  name: '',
  password: '',
  status: 'active',
  role_ids: [] as string[],
})

// 重置密码弹窗
const resetPwdVisible = ref(false)
const resetPwdId = ref('')
const resetPwdName = ref('')
const resetPwdPassword = ref('')

const roleCodeToName = computed(() => {
  const map: Record<string, string> = {}
  roles.value.forEach((role) => {
    map[role.code] = role.name
  })
  return map
})

const roleCodeToId = computed(() => {
  const map: Record<string, string> = {}
  roles.value.forEach((role) => {
    map[role.code] = role.id
  })
  return map
})

const roleOptions = computed(() =>
  roles.value.map((role) => ({ label: role.name, value: role.id })),
)

const formatTime = (value: number | null | undefined) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const roleNames = (codes: string[]) => {
  if (!codes || codes.length === 0) return []
  return codes.map((code) => roleCodeToName.value[code] || code)
}

const isSuperAdmin = (record: AdminUser) => {
  return Array.isArray(record.roles) && record.roles.includes('super_admin')
}

const columns = computed(() => [
  { title: t('admin.adminUsers.username'), slotName: 'username' },
  { title: t('admin.adminUsers.name'), slotName: 'name' },
  { title: t('admin.adminUsers.email'), slotName: 'email' },
  { title: t('admin.adminUsers.role'), slotName: 'role' },
  { title: t('admin.adminUsers.status'), slotName: 'status' },
  { title: t('admin.adminUsers.onlineStatus'), slotName: 'online_status' },
  { title: t('admin.adminUsers.createdAt'), slotName: 'created_at' },
  { title: t('admin.adminUsers.lastLogin'), slotName: 'last_login_at' },
  { title: t('admin.adminUsers.actions'), slotName: 'actions', width: 280 },
])

const loadRoles = async () => {
  try {
    const res = await listRoles()
    roles.value = res.data || []
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.adminUsers.loadRolesFailed')))
  }
}

const loadAdmins = async () => {
  loading.value = true
  try {
    const res = await listAdminUsers({
      search: filters.value.search,
      status: filters.value.status,
      current_page: filters.value.current_page,
      page_size: filters.value.page_size,
    })
    admins.value = res.data.list || []
    total.value = res.data.paginator.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.adminUsers.loadAdminsFailed')))
  } finally {
    loading.value = false
  }
}

const handleSearch = async () => {
  filters.value.current_page = 1
  await loadAdmins()
}

const onPageChange = async (page: number) => {
  filters.value.current_page = page
  await loadAdmins()
}

const onPageSizeChange = async (size: number) => {
  filters.value.page_size = size
  filters.value.current_page = 1
  await loadAdmins()
}

const openCreate = () => {
  editMode.value = false
  editingId.value = ''
  form.value = {
    username: '',
    email: '',
    name: '',
    password: '',
    status: 'active',
    role_ids: [],
  }
  modalVisible.value = true
}

const openEdit = (admin: AdminUser) => {
  editMode.value = true
  editingId.value = admin.id
  form.value = {
    username: admin.username,
    email: admin.email,
    name: admin.name,
    password: '',
    status: admin.status,
    role_ids: (admin.roles || [])
      .map((code) => roleCodeToId.value[code])
      .filter((id): id is string => !!id),
  }
  modalVisible.value = true
}

const submit = async () => {
  if (!form.value.name) {
    Message.warning(t('admin.adminUsers.nameRequired'))
    return
  }
  if (!editMode.value && !form.value.password) {
    Message.warning(t('admin.adminUsers.passwordRequired'))
    return
  }
  actionLoading.value = true
  try {
    if (editMode.value) {
      await updateAdminUser(editingId.value, {
        name: form.value.name,
        email: form.value.email,
        status: form.value.status,
        role_ids: form.value.role_ids,
      })
      Message.success(t('admin.adminUsers.updated'))
    } else {
      await createAdminUser({
        username: form.value.username,
        email: form.value.email,
        name: form.value.name,
        password: form.value.password,
        role_ids: form.value.role_ids,
      })
      Message.success(t('admin.adminUsers.created'))
    }
    modalVisible.value = false
    await loadAdmins()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.adminUsers.saveFailed')))
  } finally {
    actionLoading.value = false
  }
}

const handleDisable = async (admin: AdminUser) => {
  actionLoading.value = true
  try {
    await disableAdminUser(admin.id)
    Message.success(t('admin.adminUsers.adminDisabled'))
    await loadAdmins()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.adminUsers.disableFailed')))
  } finally {
    actionLoading.value = false
  }
}

const handleEnable = async (admin: AdminUser) => {
  actionLoading.value = true
  try {
    await enableAdminUser(admin.id)
    Message.success(t('admin.adminUsers.adminEnabled'))
    await loadAdmins()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.adminUsers.enableFailed')))
  } finally {
    actionLoading.value = false
  }
}

const handleRevokeSessions = async (record: AdminUser) => {
  actionLoading.value = true
  try {
    const response = await revokeAdminUserSessions(record.id)
    Message.success(t('admin.adminUsers.sessionsRevoked', { count: response.data.revoked_sessions }))
    await loadAdmins()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.adminUsers.revokeSessionsFailed')))
  } finally {
    actionLoading.value = false
  }
}

const openResetPwd = (admin: AdminUser) => {
  resetPwdId.value = admin.id
  resetPwdName.value = admin.username || admin.name
  resetPwdPassword.value = ''
  resetPwdVisible.value = true
}

const submitResetPwd = async () => {
  if (!resetPwdPassword.value) {
    Message.warning(t('admin.adminUsers.passwordRequired'))
    return
  }
  actionLoading.value = true
  try {
    await resetAdminUserPassword(resetPwdId.value, resetPwdPassword.value)
    Message.success(t('admin.adminUsers.passwordReset'))
    resetPwdVisible.value = false
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.adminUsers.resetPasswordFailed')))
  } finally {
    actionLoading.value = false
  }
}

onMounted(async () => {
  await loadRoles()
  await loadAdmins()
})
</script>

<template>
  <section class="space-y-6 p-6">
    <header class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-semibold text-gray-900">{{ t('admin.adminUsers.title') }}</h1>
        <p class="mt-1 text-sm text-gray-500">{{ t('admin.adminUsers.description') }}</p>
      </div>
      <a-button type="primary" @click="openCreate">{{ t('admin.adminUsers.createAdmin') }}</a-button>
    </header>

    <div class="rounded-lg border bg-white p-4">
      <div class="grid gap-3 md:grid-cols-4">
        <a-input v-model="filters.search" :placeholder="t('admin.adminUsers.searchPlaceholder')" allow-clear @press-enter="handleSearch" />
        <a-select v-model="filters.status" :options="statusOptions" />
        <a-button type="primary" :loading="loading" @click="handleSearch">{{ t('admin.adminUsers.search') }}</a-button>
      </div>
    </div>

    <a-table
      :loading="loading"
      :data="admins"
      :columns="columns"
      :pagination="false"
      :bordered="{ wrapper: true, cell: true }"
      row-key="id"
    >
      <template #columns>
        <a-table-column v-for="col of columns" :key="col.slotName" :title="col.title" :width="col.width">
          <template #cell="{ record }">
            <template v-if="col.slotName === 'username'">{{ record.username || '-' }}</template>
            <template v-else-if="col.slotName === 'name'">{{ record.name || '-' }}</template>
            <template v-else-if="col.slotName === 'email'">{{ record.email || '-' }}</template>
            <template v-else-if="col.slotName === 'role'">
              <a-tag v-for="name in roleNames(record.roles)" :key="name" size="small" color="arcoblue">{{ name }}</a-tag>
              <span v-if="!roleNames(record.roles).length" class="text-gray-400">-</span>
            </template>
            <template v-else-if="col.slotName === 'status'">
              <a-tag v-if="record.status === 'active'" size="small" color="green">{{ t('admin.adminUsers.tagActive') }}</a-tag>
              <a-tag v-else-if="record.status === 'disabled'" size="small" color="red">{{ t('admin.adminUsers.tagDisabled') }}</a-tag>
              <a-tag v-else size="small" color="orange">{{ record.status }}</a-tag>
            </template>
            <template v-else-if="col.slotName === 'online_status'">
              <a-tag v-if="record.is_online" size="small" color="green">{{ t('admin.adminUsers.online') }}</a-tag>
              <a-tag v-else size="small" color="gray">{{ t('admin.adminUsers.offline') }}</a-tag>
            </template>
            <template v-else-if="col.slotName === 'created_at'">{{ formatTime(record.created_at) }}</template>
            <template v-else-if="col.slotName === 'last_login_at'">
              <div>{{ formatTime(record.last_login_at) }}</div>
              <div v-if="record.last_login_ip" class="text-xs text-gray-400">{{ record.last_login_ip }}</div>
            </template>
            <template v-else-if="col.slotName === 'actions'">
              <a-space>
                <a-button v-if="canUpdateAdmin" size="mini" @click="openEdit(record)">{{ t('admin.adminUsers.edit') }}</a-button>
                <a-button v-if="canManageAdmin && !isSuperAdmin(record)" size="mini" @click="openResetPwd(record)">{{ t('admin.adminUsers.resetPassword') }}</a-button>
                <a-button
                  v-if="canManageAdmin && record.is_online && !isSuperAdmin(record)"
                  size="mini"
                  status="warning"
                  :loading="actionLoading"
                  @click="handleRevokeSessions(record)"
                >{{ t('admin.adminUsers.revokeSessions') }}</a-button>
                <a-button
                  v-if="canManageAdmin && record.status === 'active' && !isSuperAdmin(record)"
                  size="mini"
                  status="danger"
                  :loading="actionLoading"
                  @click="handleDisable(record)"
                >{{ t('admin.adminUsers.disable') }}</a-button>
                <a-button
                  v-else-if="canManageAdmin && record.status === 'disabled'"
                  size="mini"
                  type="primary"
                  :loading="actionLoading"
                  @click="handleEnable(record)"
                >{{ t('admin.adminUsers.enable') }}</a-button>
              </a-space>
            </template>
          </template>
        </a-table-column>
      </template>
    </a-table>

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

    <!-- 新建/编辑管理员弹窗 -->
    <a-modal
      v-model:visible="modalVisible"
      :title="editMode ? t('admin.adminUsers.editTitle') : t('admin.adminUsers.createTitle')"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submit"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item :label="t('admin.adminUsers.username')" field="username">
          <a-input v-model="form.username" :disabled="editMode" :placeholder="t('admin.adminUsers.usernamePlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('admin.adminUsers.email')" field="email">
          <a-input v-model="form.email" :placeholder="t('admin.adminUsers.emailPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('admin.adminUsers.name')" field="name">
          <a-input v-model="form.name" :placeholder="t('admin.adminUsers.namePlaceholder')" />
        </a-form-item>
        <a-form-item v-if="!editMode" :label="t('admin.adminUsers.password')" field="password">
          <a-input v-model="form.password" :placeholder="t('admin.adminUsers.passwordPlaceholder')" />
        </a-form-item>
        <a-form-item v-if="editMode" :label="t('admin.adminUsers.status')" field="status">
          <a-select v-model="form.status">
            <a-option value="active">{{ t('admin.adminUsers.tagActive') }}</a-option>
            <a-option value="disabled">{{ t('admin.adminUsers.tagDisabled') }}</a-option>
            <a-option value="pending">{{ t('admin.adminUsers.statusPending') }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.adminUsers.role')" field="role_ids">
          <a-select
            v-model="form.role_ids"
            :options="roleOptions"
            multiple
            allow-search
            :placeholder="t('admin.adminUsers.rolePlaceholder')"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 重置密码弹窗 -->
    <a-modal
      v-model:visible="resetPwdVisible"
      :title="t('admin.adminUsers.resetPasswordTitle', { name: resetPwdName })"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submitResetPwd"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('admin.adminUsers.password')" field="password">
          <a-input v-model="resetPwdPassword" :placeholder="t('admin.adminUsers.passwordPlaceholder')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>