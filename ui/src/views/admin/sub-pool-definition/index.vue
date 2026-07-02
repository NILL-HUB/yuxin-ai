<script setup lang="ts">
defineOptions({ name: 'SubPoolDefinitionView' })

import { onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  createSubPoolDefinition,
  deleteSubPoolDefinition,
  listSubPoolDefinitions,
  setSubPoolDefinitionStatus,
  updateSubPoolDefinition,
  type SubPoolDefinition,
  type SubPoolType,
} from '@/services/sub-pool-definition'
import { getErrorMessage } from '@/utils/error'

const POOL_TYPE_OPTIONS = [
  { label: '全部类型', value: '' },
  { label: 'Agent 子池', value: 'agent' },
  { label: 'Tool 子池', value: 'tool' },
]

const ENABLED_OPTIONS = [
  { label: '全部状态', value: '' },
  { label: '已启用', value: 'true' },
  { label: '已禁用', value: 'false' },
]

const loading = ref(false)
const actionLoading = ref(false)
const list = ref<SubPoolDefinition[]>([])
const total = ref(0)

const filters = ref({
  pool_type: '' as SubPoolType | '',
  enabled: '' as '' | 'true' | 'false',
  keyword: '',
  current_page: 1,
  page_size: 20,
})

const modalVisible = ref(false)
const editMode = ref(false)
const editingId = ref('')
const form = ref({
  pool_type: 'agent' as SubPoolType,
  name: '',
  label: '',
  description: '',
  visible_to_user: true,
  default_enabled: false,
  default_capabilities: [] as string[],
  task_keywords: [] as string[],
  sort_order: 0,
})

const loadList = async () => {
  loading.value = true
  try {
    const enabledParam: boolean | undefined =
      filters.value.enabled === '' ? undefined : filters.value.enabled === 'true'
    const res = await listSubPoolDefinitions({
      pool_type: filters.value.pool_type || undefined,
      enabled: enabledParam,
      keyword: filters.value.keyword || undefined,
      current_page: filters.value.current_page,
      page_size: filters.value.page_size,
    })
    list.value = res.data.list || []
    total.value = res.data.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, '加载子池定义失败'))
  } finally {
    loading.value = false
  }
}

const handleSearch = async () => {
  filters.value.current_page = 1
  await loadList()
}

const onPageChange = async (page: number) => {
  filters.value.current_page = page
  await loadList()
}

const onPageSizeChange = async (size: number) => {
  filters.value.page_size = size
  filters.value.current_page = 1
  await loadList()
}

const openCreate = () => {
  editMode.value = false
  editingId.value = ''
  form.value = {
    pool_type: 'agent',
    name: '',
    label: '',
    description: '',
    visible_to_user: true,
    default_enabled: false,
    default_capabilities: [],
    task_keywords: [],
    sort_order: 0,
  }
  modalVisible.value = true
}

const openEdit = (item: SubPoolDefinition) => {
  editMode.value = true
  editingId.value = item.id
  form.value = {
    pool_type: item.pool_type,
    name: item.name,
    label: item.label,
    description: item.description || '',
    visible_to_user: item.visible_to_user,
    default_enabled: item.default_enabled,
    default_capabilities: [...(item.default_capabilities || [])],
    task_keywords: [...(item.task_keywords || [])],
    sort_order: item.sort_order,
  }
  modalVisible.value = true
}

const submit = async () => {
  if (!form.value.name) {
    Message.warning('请填写名称')
    return
  }
  if (!form.value.label) {
    Message.warning('请填写显示名')
    return
  }
  actionLoading.value = true
  try {
    const payload = {
      pool_type: form.value.pool_type,
      name: form.value.name,
      label: form.value.label,
      description: form.value.description,
      visible_to_user: form.value.visible_to_user,
      default_enabled: form.value.default_enabled,
      default_capabilities: form.value.default_capabilities,
      task_keywords: form.value.task_keywords,
      sort_order: form.value.sort_order,
    }
    if (editMode.value) {
      await updateSubPoolDefinition(editingId.value, payload)
      Message.success('子池定义已更新')
    } else {
      await createSubPoolDefinition(payload)
      Message.success('子池定义已创建')
    }
    modalVisible.value = false
    await loadList()
  } catch (error) {
    Message.error(getErrorMessage(error, '保存子池定义失败'))
  } finally {
    actionLoading.value = false
  }
}

const toggleStatus = async (item: SubPoolDefinition, enabled: boolean) => {
  actionLoading.value = true
  try {
    await setSubPoolDefinitionStatus(item.id, enabled)
    Message.success(enabled ? '已启用' : '已禁用')
    await loadList()
  } catch (error) {
    Message.error(getErrorMessage(error, '更新状态失败'))
  } finally {
    actionLoading.value = false
  }
}

const remove = async (item: SubPoolDefinition) => {
  if (item.is_system) {
    Message.warning('内置池不可删除')
    return
  }
  actionLoading.value = true
  try {
    await deleteSubPoolDefinition(item.id)
    Message.success('子池定义已删除')
    await loadList()
  } catch (error) {
    Message.error(getErrorMessage(error, '删除子池定义失败'))
  } finally {
    actionLoading.value = false
  }
}

onMounted(loadList)
</script>

<template>
  <section class="space-y-6 p-6">
    <header class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-semibold text-gray-900">子池定义管理</h1>
        <p class="mt-1 text-sm text-gray-500">维护 Agent 子池与 Tool 子池的定义、默认能力与任务关键词。</p>
      </div>
      <a-button type="primary" @click="openCreate">新建子池定义</a-button>
    </header>

    <div class="rounded-lg border bg-white p-4">
      <div class="grid gap-3 md:grid-cols-4">
        <a-select v-model="filters.pool_type" :options="POOL_TYPE_OPTIONS" />
        <a-select v-model="filters.enabled" :options="ENABLED_OPTIONS" />
        <a-input
          v-model="filters.keyword"
          placeholder="搜索名称或显示名"
          allow-clear
          @press-enter="handleSearch"
        />
        <a-button type="primary" :loading="loading" @click="handleSearch">查询</a-button>
      </div>
    </div>

    <a-spin :loading="loading" class="block">
      <div class="overflow-x-auto rounded-lg border bg-white">
        <table class="w-full text-left text-sm">
          <thead class="bg-gray-50 text-gray-500">
            <tr>
              <th class="p-3">池类型</th>
              <th class="p-3">名称</th>
              <th class="p-3">显示名</th>
              <th class="p-3">描述</th>
              <th class="p-3">用户可见</th>
              <th class="p-3">默认启用</th>
              <th class="p-3">关键词数量</th>
              <th class="p-3">排序</th>
              <th class="p-3">状态</th>
              <th class="p-3">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!list.length">
              <td class="p-6 text-center text-gray-400" colspan="10">暂无子池定义数据</td>
            </tr>
            <tr v-for="item in list" :key="item.id" class="border-t">
              <td class="p-3">
                <a-tag :color="item.pool_type === 'agent' ? 'arcoblue' : 'purple'" size="small">
                  {{ item.pool_type === 'agent' ? 'Agent' : 'Tool' }}
                </a-tag>
              </td>
              <td class="p-3 font-mono">
                {{ item.name }}
                <a-tag v-if="item.is_system" size="small" color="gray">内置</a-tag>
              </td>
              <td class="p-3">{{ item.label || '-' }}</td>
              <td class="p-3 max-w-xs truncate text-gray-500" :title="item.description">
                {{ item.description || '-' }}
              </td>
              <td class="p-3">
                <a-tag :color="item.visible_to_user ? 'green' : 'gray'" size="small">
                  {{ item.visible_to_user ? '是' : '否' }}
                </a-tag>
              </td>
              <td class="p-3">
                <a-tag :color="item.default_enabled ? 'green' : 'gray'" size="small">
                  {{ item.default_enabled ? '是' : '否' }}
                </a-tag>
              </td>
              <td class="p-3">{{ item.task_keywords?.length || 0 }}</td>
              <td class="p-3">{{ item.sort_order }}</td>
              <td class="p-3">
                <a-tag :color="item.enabled ? 'green' : 'red'" size="small">
                  {{ item.enabled ? '启用' : '禁用' }}
                </a-tag>
              </td>
              <td class="p-3">
                <a-space>
                  <a-button size="mini" @click="openEdit(item)">编辑</a-button>
                  <a-button
                    v-if="!item.enabled"
                    size="mini"
                    type="primary"
                    :loading="actionLoading"
                    @click="toggleStatus(item, true)"
                  >启用</a-button>
                  <a-button
                    v-else
                    size="mini"
                    :loading="actionLoading"
                    @click="toggleStatus(item, false)"
                  >禁用</a-button>
                  <a-tooltip v-if="item.is_system" content="内置池不可删除">
                    <span>
                      <a-button size="mini" status="danger" disabled>删除</a-button>
                    </span>
                  </a-tooltip>
                  <a-button
                    v-else
                    size="mini"
                    status="danger"
                    :loading="actionLoading"
                    @click="remove(item)"
                  >删除</a-button>
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
        :page-size-options="[10, 20, 50, 100]"
        @change="onPageChange"
        @page-size-change="onPageSizeChange"
      />
    </div>

    <a-modal
      v-model:visible="modalVisible"
      :title="editMode ? '编辑子池定义' : '新建子池定义'"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submit"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item label="池类型" field="pool_type">
          <a-select v-model="form.pool_type" :disabled="editMode">
            <a-option value="agent">Agent</a-option>
            <a-option value="tool">Tool</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="名称" field="name">
          <a-input v-model="form.name" :disabled="editMode" placeholder="子池唯一标识，如 tenant_agent" />
        </a-form-item>
        <a-form-item label="显示名" field="label">
          <a-input v-model="form.label" placeholder="面向用户的显示名称" />
        </a-form-item>
        <a-form-item label="描述" field="description">
          <a-textarea v-model="form.description" placeholder="子池用途说明" :auto-size="{ minRows: 2, maxRows: 4 }" allow-clear />
        </a-form-item>
        <a-form-item label="用户可见" field="visible_to_user">
          <a-switch v-model="form.visible_to_user" />
        </a-form-item>
        <a-form-item label="默认启用" field="default_enabled">
          <a-switch v-model="form.default_enabled" />
        </a-form-item>
        <a-form-item label="默认能力" field="default_capabilities">
          <a-input-tag v-model="form.default_capabilities" placeholder="输入能力标签后回车" allow-clear />
        </a-form-item>
        <a-form-item label="任务关键词" field="task_keywords">
          <a-input-tag v-model="form.task_keywords" placeholder="输入关键词后回车" allow-clear />
        </a-form-item>
        <a-form-item label="排序" field="sort_order">
          <a-input-number v-model="form.sort_order" :min="0" :step="1" />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
