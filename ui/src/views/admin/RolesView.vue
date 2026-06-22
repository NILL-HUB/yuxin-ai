<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  createRole,
  deleteRole,
  listPermissions,
  listRoles,
  updateRole,
  type Permission,
  type Role,
} from '@/services/admin-roles'
import { getErrorMessage } from '@/utils/error'

const loading = ref(false)
const actionLoading = ref(false)
const roles = ref<Role[]>([])
const permissions = ref<Permission[]>([])

const modalVisible = ref(false)
const editMode = ref(false)
const editingId = ref('')
const form = ref({
  code: '',
  name: '',
  description: '',
  permission_ids: [] as string[],
})

const permissionCodeToId = computed(() => {
  const map: Record<string, string> = {}
  permissions.value.forEach((permission) => {
    map[permission.code] = permission.id
  })
  return map
})

const permissionGroups = computed(() => {
  const groups: Record<string, Permission[]> = {}
  permissions.value.forEach((permission) => {
    const key = permission.resource || '其他'
    if (!groups[key]) groups[key] = []
    groups[key].push(permission)
  })
  return Object.entries(groups).map(([resource, items]) => ({ resource, items }))
})

const loadRoles = async () => {
  loading.value = true
  try {
    const res = await listRoles()
    roles.value = res.data || []
  } catch (error) {
    Message.error(getErrorMessage(error, '加载角色失败'))
  } finally {
    loading.value = false
  }
}

const loadPermissions = async () => {
  try {
    const res = await listPermissions()
    permissions.value = res.data || []
  } catch (error) {
    Message.error(getErrorMessage(error, '加载权限失败'))
  }
}

const openCreate = () => {
  editMode.value = false
  editingId.value = ''
  form.value = { code: '', name: '', description: '', permission_ids: [] }
  modalVisible.value = true
}

const openEdit = (role: Role) => {
  editMode.value = true
  editingId.value = role.id
  form.value = {
    code: role.code,
    name: role.name,
    description: role.description || '',
    permission_ids: (role.permissions || [])
      .map((code) => permissionCodeToId.value[code])
      .filter((id): id is string => !!id),
  }
  modalVisible.value = true
}

const submit = async () => {
  if (!editMode.value && !form.value.code) {
    Message.warning('请填写角色编码')
    return
  }
  if (!form.value.name) {
    Message.warning('请填写角色名称')
    return
  }
  actionLoading.value = true
  try {
    if (editMode.value) {
      await updateRole(editingId.value, {
        name: form.value.name,
        description: form.value.description,
        permission_ids: form.value.permission_ids,
      })
      Message.success('角色已更新')
    } else {
      await createRole({
        code: form.value.code,
        name: form.value.name,
        description: form.value.description,
        permission_ids: form.value.permission_ids,
      })
      Message.success('角色已创建')
    }
    modalVisible.value = false
    await loadRoles()
  } catch (error) {
    Message.error(getErrorMessage(error, '保存角色失败'))
  } finally {
    actionLoading.value = false
  }
}

const handleDelete = async (role: Role) => {
  actionLoading.value = true
  try {
    await deleteRole(role.id)
    Message.success('角色已删除')
    await loadRoles()
  } catch (error) {
    Message.error(getErrorMessage(error, '删除角色失败'))
  } finally {
    actionLoading.value = false
  }
}

onMounted(async () => {
  await loadPermissions()
  await loadRoles()
})
</script>

<template>
  <section class="space-y-6 p-6">
    <header class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-semibold text-gray-900">角色权限</h1>
        <p class="mt-1 text-sm text-gray-500">管理后台角色与权限点分配，系统角色不可删除。</p>
      </div>
      <a-button type="primary" @click="openCreate">新建角色</a-button>
    </header>

    <a-spin :loading="loading" class="block">
      <div class="overflow-hidden rounded-lg border bg-white">
        <table class="w-full text-left text-sm">
          <thead class="bg-gray-50 text-gray-500">
            <tr>
              <th class="p-3">角色编码</th>
              <th class="p-3">名称</th>
              <th class="p-3">描述</th>
              <th class="p-3">系统角色</th>
              <th class="p-3">权限数量</th>
              <th class="p-3">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!roles.length">
              <td class="p-6 text-center text-gray-400" colspan="6">暂无角色数据</td>
            </tr>
            <tr v-for="role in roles" :key="role.id" class="border-t">
              <td class="p-3 font-mono">{{ role.code }}</td>
              <td class="p-3">{{ role.name || '-' }}</td>
              <td class="p-3 text-gray-500">{{ role.description || '-' }}</td>
              <td class="p-3">
                <a-tag v-if="role.is_system" size="small" color="arcoblue">系统</a-tag>
                <a-tag v-else size="small" color="gray">自定义</a-tag>
              </td>
              <td class="p-3">{{ role.permissions?.length || 0 }}</td>
              <td class="p-3">
                <a-space>
                  <a-button size="mini" @click="openEdit(role)">编辑</a-button>
                  <a-button
                    size="mini"
                    status="danger"
                    :disabled="role.is_system"
                    :loading="actionLoading"
                    @click="handleDelete(role)"
                  >删除</a-button>
                </a-space>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </a-spin>

    <a-modal
      v-model:visible="modalVisible"
      :title="editMode ? '编辑角色' : '新建角色'"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submit"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item label="角色编码" field="code">
          <a-input v-model="form.code" :disabled="editMode" placeholder="小写字母开头，仅含字母数字下划线" />
        </a-form-item>
        <a-form-item label="角色名称" field="name">
          <a-input v-model="form.name" placeholder="如 运营管理员" />
        </a-form-item>
        <a-form-item label="描述" field="description">
          <a-textarea v-model="form.description" placeholder="角色职责描述" :auto-size="{ minRows: 2, maxRows: 4 }" allow-clear />
        </a-form-item>
        <a-form-item label="权限" field="permission_ids">
          <a-select
            v-model="form.permission_ids"
            multiple
            allow-search
            placeholder="选择权限点"
            :virtual-list-props="{ height: 240 }"
          >
            <a-option-group v-for="group in permissionGroups" :key="group.resource" :label="group.resource">
              <a-option v-for="item in group.items" :key="item.id" :value="item.id">{{ item.name }}</a-option>
            </a-option-group>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
