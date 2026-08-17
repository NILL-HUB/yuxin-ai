<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
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

const { t } = useI18n()

const loading = ref(false)
const actionLoading = ref(false)
const roles = ref<Role[]>([])
const permissions = ref<Permission[]>([])

const permissionByCode = computed(() => {
  const map: Record<string, Permission> = {}
  permissions.value.forEach((permission) => {
    map[permission.code] = permission
  })
  return map
})

const permissionLabel = (code: string) => permissionByCode.value[code]?.name || code

const modalVisible = ref(false)
const editMode = ref(false)
const editingCode = ref('')
const form = ref({
  code: '',
  name: '',
  description: '',
  permission_codes: [] as string[],
})

const resourceLabel = (resource: string) => {
  const key = `admin.roles.resources.${resource}`
  const label = t(key)
  return label === key ? resource : label
}

const permissionGroups = computed(() => {
  const groups: Record<string, Permission[]> = {}
  permissions.value.forEach((permission) => {
    const key = permission.resource || t('admin.roles.otherPermission')
    if (!groups[key]) groups[key] = []
    groups[key].push(permission)
  })
  return Object.entries(groups).map(([resource, items]) => ({
    isGroup: true,
    label: resourceLabel(resource),
    options: items.map((item) => ({ value: item.code, label: item.name })),
  }))
})

const loadRoles = async () => {
  loading.value = true
  try {
    const res = await listRoles()
    roles.value = res.data || []
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.roles.loadRolesFailed')))
  } finally {
    loading.value = false
  }
}

const loadPermissions = async () => {
  try {
    const res = await listPermissions()
    permissions.value = res.data || []
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.roles.loadPermissionsFailed')))
  }
}

const openCreate = () => {
  editMode.value = false
  editingCode.value = ''
  form.value = { code: '', name: '', description: '', permission_codes: [] }
  modalVisible.value = true
}

const openEdit = (role: Role) => {
  editMode.value = true
  editingCode.value = role.code
  form.value = {
    code: role.code,
    name: role.name,
    description: role.description || '',
    permission_codes: role.permissions || [],
  }
  modalVisible.value = true
}

const submit = async () => {
  if (!editMode.value && !form.value.code) {
    Message.warning(t('admin.roles.codeRequired'))
    return
  }
  if (!form.value.name) {
    Message.warning(t('admin.roles.nameRequired'))
    return
  }
  actionLoading.value = true
  try {
    if (editMode.value) {
      await updateRole(editingCode.value, {
        name: form.value.name,
        description: form.value.description,
        permission_codes: form.value.permission_codes,
      })
      Message.success(t('admin.roles.updated'))
    } else {
      await createRole({
        code: form.value.code,
        name: form.value.name,
        description: form.value.description,
        permission_codes: form.value.permission_codes,
      })
      Message.success(t('admin.roles.created'))
    }
    modalVisible.value = false
    await loadRoles()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.roles.saveFailed')))
  } finally {
    actionLoading.value = false
  }
}

const handleDelete = async (role: Role) => {
  actionLoading.value = true
  try {
    await deleteRole(role.code)
    Message.success(t('admin.roles.deleted'))
    await loadRoles()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.roles.deleteFailed')))
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
        <h1 class="text-2xl font-semibold text-gray-900">{{ t('admin.roles.title') }}</h1>
        <p class="mt-1 text-sm text-gray-500">{{ t('admin.roles.description') }}</p>
      </div>
      <a-button type="primary" @click="openCreate">{{ t('admin.roles.createRole') }}</a-button>
    </header>

    <a-spin :loading="loading" class="block">
      <div class="overflow-hidden rounded-lg border bg-white">
        <table class="w-full text-left text-sm">
          <thead class="bg-gray-50 text-gray-500">
            <tr>
              <th class="p-3">{{ t('admin.roles.code') }}</th>
              <th class="p-3">{{ t('admin.roles.name') }}</th>
              <th class="p-3">{{ t('admin.roles.descriptionLabel') }}</th>
              <th class="p-3">{{ t('admin.roles.isSystem') }}</th>
              <th class="p-3">{{ t('admin.roles.permissionCount') }}</th>
              <th class="p-3">{{ t('admin.roles.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!roles.length">
              <td class="p-6 text-center text-gray-400" colspan="6">{{ t('admin.roles.empty') }}</td>
            </tr>
            <tr v-for="role in roles" :key="role.code" class="border-t">
              <td class="p-3 font-mono">{{ role.code }}</td>
              <td class="p-3">{{ role.name || '-' }}</td>
              <td class="p-3 text-gray-500">{{ role.description || '-' }}</td>
              <td class="p-3">
                <a-tag v-if="role.is_system" size="small" color="arcoblue">{{ t('admin.roles.systemTag') }}</a-tag>
                <a-tag v-else size="small" color="gray">{{ t('admin.roles.customTag') }}</a-tag>
              </td>
              <td class="p-3">{{ role.permissions?.length || 0 }}</td>
              <td class="p-3">
                <a-space>
                  <a-button size="mini" @click="openEdit(role)">{{ t('admin.roles.edit') }}</a-button>
                  <a-button
                    size="mini"
                    status="danger"
                    :disabled="role.is_system"
                    :loading="actionLoading"
                    @click="handleDelete(role)"
                  >{{ t('admin.roles.remove') }}</a-button>
                </a-space>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </a-spin>

    <a-modal
      v-model:visible="modalVisible"
      :title="editMode ? t('admin.roles.editTitle') : t('admin.roles.createTitle')"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submit"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item :label="t('admin.roles.code')" field="code">
          <a-input v-model="form.code" :disabled="editMode" :placeholder="t('admin.roles.codePlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('admin.roles.name')" field="name">
          <a-input v-model="form.name" :placeholder="t('admin.roles.namePlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('admin.roles.descriptionLabel')" field="description">
          <a-textarea v-model="form.description" :placeholder="t('admin.roles.descriptionPlaceholder')" :auto-size="{ minRows: 2, maxRows: 4 }" allow-clear />
        </a-form-item>
        <a-form-item :label="t('admin.roles.permissions')" field="permission_codes">
          <a-select
            v-model="form.permission_codes"
            multiple
            allow-search
            :options="permissionGroups"
            :placeholder="t('admin.roles.permissionPlaceholder')"
            :virtual-list-props="{ height: 240 }"
          >
            <template #label="{ data }">
              {{ permissionLabel(data.value) }}
            </template>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
