<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import { useAdminStore } from '@/stores/admin'
import {
  listCliProviders,
  updateCliProvider,
  deleteCliProvider,
  type CliProvider,
} from '@/services/admin-cli'
import CreateOrUpdateCliModal from '@/views/admin/cli/CreateOrUpdateCliModal.vue'

const { t } = useI18n()
const adminStore = useAdminStore()

const loading = ref(false)
const items = ref<CliProvider[]>([])
const keyword = ref('')
const categoryFilter = ref('')
const modalVisible = ref(false)
const editing = ref<CliProvider | null>(null)

const canCreate = computed(() => adminStore.hasPermission('cli:create'))
const canUpdate = computed(() => adminStore.hasPermission('cli:update'))
const canDelete = computed(() => adminStore.hasPermission('cli:delete'))

const categories = computed(() => {
  const set = new Set(items.value.map((item) => item.category).filter(Boolean))
  return [...set].sort()
})

const filtered = computed(() => {
  let list = items.value
  if (categoryFilter.value) {
    list = list.filter((item) => item.category === categoryFilter.value)
  }
  const query = keyword.value.trim().toLowerCase()
  if (!query) return list
  return list.filter((item) =>
    [item.name, item.label, item.command].some((field) =>
      String(field || '').toLowerCase().includes(query),
    ),
  )
})

const loadData = async () => {
  loading.value = true
  try {
    items.value = await listCliProviders()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.adminCli.loadFailed')))
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editing.value = null
  modalVisible.value = true
}

const openEdit = (item: CliProvider) => {
  editing.value = item
  modalVisible.value = true
}

const toggleEnabled = async (item: CliProvider, value: boolean) => {
  try {
    await updateCliProvider(item.id, { enabled: value })
  } catch (error) {
    item.enabled = !value
    Message.error(getErrorMessage(error, t('admin.adminCli.statusFailed')))
  }
}

const confirmDelete = (item: CliProvider) => {
  Modal.confirm({
    title: t('admin.adminCli.deleteConfirmTitle'),
    content: t('admin.adminCli.deleteConfirmContent', { name: item.name }),
    onOk: async () => {
      try {
        await deleteCliProvider(item.id)
        Message.success(t('admin.adminCli.deleted'))
        await loadData()
      } catch (error) {
        Message.error(getErrorMessage(error, t('admin.adminCli.deleteFailed')))
      }
    },
  })
}

onMounted(loadData)
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-4">
      <div>
        <h1 class="text-2xl font-bold">{{ t('admin.adminCli.title') }}</h1>
        <p class="text-gray-600 text-sm mt-1">{{ t('admin.adminCli.description') }}</p>
      </div>
      <button
        v-if="canCreate"
        class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm"
        @click="openCreate"
      >
        {{ t('admin.adminCli.register') }}
      </button>
    </div>

    <div class="flex items-center gap-3 mb-4">
      <a-select v-model="categoryFilter" class="w-40">
        <a-option value="">{{ t('admin.adminCli.categoryAll') }}</a-option>
        <a-option v-for="c in categories" :key="c" :value="c">{{ c }}</a-option>
      </a-select>
      <a-input
        v-model="keyword"
        data-test="search"
        class="w-64"
        :placeholder="t('admin.adminCli.searchPlaceholder')"
        allow-clear
      />
    </div>

    <div v-if="loading" class="text-center py-8 text-gray-500">{{ t('common.loading') }}</div>

    <div v-else-if="!filtered.length" class="text-center py-8 text-gray-500">
      {{ t('admin.adminCli.empty') }}
    </div>

    <template v-else>
      <p class="text-gray-500 text-sm mb-2">
        {{ t('admin.adminCli.total', { count: filtered.length }) }}
      </p>
      <div class="space-y-3">
        <div
          v-for="item in filtered"
          :key="item.id"
          class="border rounded-lg p-4 hover:shadow-sm transition-shadow flex items-center justify-between gap-4"
        >
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="font-medium">{{ item.label || item.name }}</span>
              <span class="text-xs text-gray-400">{{ item.name }}</span>
              <span class="text-xs px-2 py-0.5 rounded bg-gray-100">{{ item.category }}</span>
              <span class="text-xs px-2 py-0.5 rounded bg-blue-50 text-blue-600">
                {{ t('admin.adminCli.columns.tools') }}: {{ item.tool_count }}
              </span>
            </div>
            <div class="text-sm text-gray-600 mt-1 font-mono truncate">
              {{ item.command }} {{ (item.args || []).join(' ') }}
            </div>
            <div v-if="(item.task_keywords || []).length" class="flex flex-wrap gap-1 mt-1">
              <span
                v-for="k in item.task_keywords"
                :key="k"
                class="text-xs px-1.5 py-0.5 rounded bg-gray-50 border border-gray-200"
              >
                {{ k }}
              </span>
            </div>
          </div>
          <div class="flex items-center gap-3 flex-none">
            <a-switch
              v-if="canUpdate"
              :model-value="item.enabled"
              @change="(value: unknown) => toggleEnabled(item, Boolean(value))"
            />
            <button v-if="canUpdate" class="text-sm text-blue-600" @click="openEdit(item)">
              {{ t('admin.adminCli.edit') }}
            </button>
            <button
              v-if="canDelete"
              class="text-sm text-red-600 delete-btn"
              @click="confirmDelete(item)"
            >
              {{ t('admin.adminCli.remove') }}
            </button>
          </div>
        </div>
      </div>
    </template>

    <CreateOrUpdateCliModal
      v-model:visible="modalVisible"
      :provider="editing"
      @saved="loadData"
    />
  </div>
</template>
