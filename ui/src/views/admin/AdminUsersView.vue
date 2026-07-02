<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  createAdminUser,
  disableAdminUser,
  listAdminUsers,
  updateAdminUser,
  type AdminUser,
} from '@/services/admin-admin-users'
import { listRoles, type Role } from '@/services/admin-roles'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()

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

    <a-spin :loading="loading" class="block">
      <div class="overflow-hidden rounded-lg border bg-white">
        <table class="w-full text-left text-sm">
          <thead class="bg-gray-50 text-gray-500">
            <tr>
              <th class="p-3">{{ t('admin.adminUsers.username') }}</th>
              <th class="p-3">{{ t('admin.adminUsers.name') }}</th>
              <th class="p-3">{{ t('admin.adminUsers.email') }}</th>
              <th class="p-3">{{ t('admin.adminUsers.role') }}</th>
              <th class="p-3">{{ t('admin.adminUsers.status') }}</th>
              <th class="p-3">{{ t('admin.adminUsers.createdAt') }}</th>
              <th class="p-3">{{ t('admin.adminUsers.lastLogin') }}</th>
              <th class="p-3">{{ t('admin.adminUsers.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!admins.length">
              <td class="p-6 text-center text-gray-400" colspan="8">{{ t('admin.adminUsers.empty') }}</td>
            </tr>
            <tr v-for="admin in admins" :key="admin.id" class="border-t">
              <td class="p-3">{{ admin.username || '-' }}</td>
              <td class="p-3">{{ admin.name || '-' }}</td>
              <td class="p-3">{{ admin.email || '-' }}</td>
              <td class="p-3">
                <a-tag v-for="name in roleNames(admin.roles)" :key="name" size="small" color="arcoblue">{{ name }}</a-tag>
                <span v-if="!roleNames(admin.roles).length" class="text-gray-400">-</span>
              </td>
              <td class="p-3">
                <a-tag v-if="admin.status === 'active'" size="small" color="green">{{ t('admin.adminUsers.tagActive') }}</a-tag>
                <a-tag v-else-if="admin.status === 'disabled'" size="small" color="red">{{ t('admin.adminUsers.tagDisabled') }}</a-tag>
                <a-tag v-else size="small" color="orange">{{ admin.status }}</a-tag>
              </td>
              <td class="p-3">{{ formatTime(admin.created_at) }}</td>
              <td class="p-3">{{ formatTime(admin.last_login_at) }}</td>
              <td class="p-3">
                <a-space>
                  <a-button size="mini" @click="openEdit(admin)">{{ t('admin.adminUsers.edit') }}</a-button>
                  <a-button
                    v-if="admin.status === 'active'"
                    size="mini"
                    status="danger"
                    :loading="actionLoading"
                    @click="handleDisable(admin)"
                  >{{ t('admin.adminUsers.disable') }}</a-button>
                </a-space>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </a-spin>

    <div class="flex justify-end">
      <a-pagination
        :total="total"
        :current="filters.current_page"
        :page-size="filters.page_size"
        show-total
        show-page-size
        @change="onPageChange"
        @page-size-change="onPageSizeChange"
      />
    </div>

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
          <a-input v-model="form.email" :disabled="editMode" :placeholder="t('admin.adminUsers.emailPlaceholder')" />
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
  </section>
</template>
