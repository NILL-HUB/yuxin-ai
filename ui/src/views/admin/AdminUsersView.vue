<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  createAdminUser,
  disableAdminUser,
  listAdminUsers,
  updateAdminUser,
  type AdminUser,
} from '@/services/admin-admin-users'
import { listRoles, type Role } from '@/services/admin-roles'
import { getErrorMessage } from '@/utils/error'

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

const statusOptions = [
  { label: '全部状态', value: 'all' },
  { label: '正常', value: 'active' },
  { label: '已禁用', value: 'disabled' },
  { label: '待激活', value: 'pending' },
]

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
    Message.error(getErrorMessage(error, '加载角色失败'))
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
    Message.error(getErrorMessage(error, '加载管理员失败'))
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
    Message.warning('请填写姓名')
    return
  }
  if (!editMode.value && !form.value.password) {
    Message.warning('请填写密码')
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
      Message.success('管理员已更新')
    } else {
      await createAdminUser({
        username: form.value.username,
        email: form.value.email,
        name: form.value.name,
        password: form.value.password,
        role_ids: form.value.role_ids,
      })
      Message.success('管理员已创建')
    }
    modalVisible.value = false
    await loadAdmins()
  } catch (error) {
    Message.error(getErrorMessage(error, '保存管理员失败'))
  } finally {
    actionLoading.value = false
  }
}

const handleDisable = async (admin: AdminUser) => {
  actionLoading.value = true
  try {
    await disableAdminUser(admin.id)
    Message.success('管理员已禁用')
    await loadAdmins()
  } catch (error) {
    Message.error(getErrorMessage(error, '禁用管理员失败'))
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
        <h1 class="text-2xl font-semibold text-gray-900">管理员管理</h1>
        <p class="mt-1 text-sm text-gray-500">维护后台管理员账号、角色绑定与状态。</p>
      </div>
      <a-button type="primary" @click="openCreate">新建管理员</a-button>
    </header>

    <div class="rounded-lg border bg-white p-4">
      <div class="grid gap-3 md:grid-cols-4">
        <a-input v-model="filters.search" placeholder="搜索用户名或邮箱" allow-clear @press-enter="handleSearch" />
        <a-select v-model="filters.status" :options="statusOptions" />
        <a-button type="primary" :loading="loading" @click="handleSearch">查询</a-button>
      </div>
    </div>

    <a-spin :loading="loading" class="block">
      <div class="overflow-hidden rounded-lg border bg-white">
        <table class="w-full text-left text-sm">
          <thead class="bg-gray-50 text-gray-500">
            <tr>
              <th class="p-3">用户名</th>
              <th class="p-3">姓名</th>
              <th class="p-3">邮箱</th>
              <th class="p-3">角色</th>
              <th class="p-3">状态</th>
              <th class="p-3">创建时间</th>
              <th class="p-3">最后登录</th>
              <th class="p-3">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!admins.length">
              <td class="p-6 text-center text-gray-400" colspan="8">暂无管理员数据</td>
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
                <a-tag v-if="admin.status === 'active'" size="small" color="green">正常</a-tag>
                <a-tag v-else-if="admin.status === 'disabled'" size="small" color="red">已禁用</a-tag>
                <a-tag v-else size="small" color="orange">{{ admin.status }}</a-tag>
              </td>
              <td class="p-3">{{ formatTime(admin.created_at) }}</td>
              <td class="p-3">{{ formatTime(admin.last_login_at) }}</td>
              <td class="p-3">
                <a-space>
                  <a-button size="mini" @click="openEdit(admin)">编辑</a-button>
                  <a-button
                    v-if="admin.status === 'active'"
                    size="mini"
                    status="danger"
                    :loading="actionLoading"
                    @click="handleDisable(admin)"
                  >禁用</a-button>
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
      :title="editMode ? '编辑管理员' : '新建管理员'"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submit"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item label="用户名" field="username">
          <a-input v-model="form.username" :disabled="editMode" placeholder="登录用户名，留空则使用邮箱" />
        </a-form-item>
        <a-form-item label="邮箱" field="email">
          <a-input v-model="form.email" :disabled="editMode" placeholder="管理员邮箱" />
        </a-form-item>
        <a-form-item label="姓名" field="name">
          <a-input v-model="form.name" placeholder="管理员姓名" />
        </a-form-item>
        <a-form-item v-if="!editMode" label="密码" field="password">
          <a-input v-model="form.password" placeholder="包含字母和数字，长度6~32位" />
        </a-form-item>
        <a-form-item v-if="editMode" label="状态" field="status">
          <a-select v-model="form.status">
            <a-option value="active">正常</a-option>
            <a-option value="disabled">已禁用</a-option>
            <a-option value="pending">待激活</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="角色" field="role_ids">
          <a-select
            v-model="form.role_ids"
            :options="roleOptions"
            multiple
            allow-search
            placeholder="选择角色"
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
