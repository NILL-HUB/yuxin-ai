<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { type AdminAppRecord, listAdminApps, updateAdminAppBasicInfo } from '@/services/admin-apps'
import { useAdminStore } from '@/stores/admin'
import { getErrorMessage } from '@/utils/error'

const router = useRouter()
const adminStore = useAdminStore()
const { t } = useI18n()

const loading = ref(false)
const saving = ref(false)
const apps = ref<AdminAppRecord[]>([])
const total = ref(0)
const filters = ref({
  current_page: 1,
  page_size: 20,
  search: '',
})
const keyword = ref('')

const modalVisible = ref(false)
const editingApp = ref<AdminAppRecord | null>(null)
const form = ref({ name: '', description: '', icon: '' })

const canUpdate = computed(() => adminStore.hasPermission('app:update'))
const hasActiveFilters = computed(() => Boolean(filters.value.search))
const emptyDescription = computed(() => {
  return hasActiveFilters.value
    ? t('admin.apps.emptyFiltered')
    : t('admin.apps.empty')
})

/**
 * 拉取后台应用分页列表。
 */
const loadApps = async () => {
  loading.value = true
  try {
    const result = await listAdminApps({
      current_page: filters.value.current_page,
      page_size: filters.value.page_size,
      search: filters.value.search.trim(),
    })
    apps.value = result.list || []
    total.value = result.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.apps.loadFailed')))
  } finally {
    loading.value = false
  }
}

/**
 * 关键字搜索：回到第一页并刷新。
 */
const handleSearch = async (value: string) => {
  keyword.value = value
  filters.value.search = value
  filters.value.current_page = 1
  await loadApps()
}

const onPageChange = (page: number) => {
  filters.value.current_page = page
  void loadApps()
}

const onPageSizeChange = (size: number) => {
  filters.value.page_size = size
  filters.value.current_page = 1
  void loadApps()
}

/**
 * 跳转到空间端应用编辑页查看详情。
 */
const handleViewDetail = async (app: AdminAppRecord) => {
  await router.push({ name: 'admin-app-edit', params: { app_id: app.id } })
}

/**
 * 打开编辑基本信息弹窗。
 */
const openEditBasic = (app: AdminAppRecord) => {
  editingApp.value = app
  form.value = {
    name: app.name || '',
    description: app.description || '',
    icon: app.icon || '',
  }
  modalVisible.value = true
}

/**
 * 提交基本信息编辑。
 */
const submitEditBasic = async () => {
  if (!editingApp.value) return
  saving.value = true
  try {
    await updateAdminAppBasicInfo(editingApp.value.id, { ...form.value })
    Message.success(t('admin.apps.saveSuccess'))
    modalVisible.value = false
    await loadApps()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.apps.saveFailed')))
  } finally {
    saving.value = false
  }
}

const formatTimestamp = (timestamp?: number) => {
  return timestamp ? new Date(timestamp * 1000).toLocaleString() : '-'
}

const statusLabel = (status?: string) => {
  if (!status) return '-'
  const key = `admin.apps.statusLabels.${status}`
  const label = t(key)
  return label === key ? status : label
}

const statusColor = (status?: string) => {
  return (
    ({ draft: 'gray', published: 'green', offline: 'red' } as Record<string, string>)[
      status || ''
    ] || 'gray'
  )
}

const riskColor = (risk?: string) =>
  ({ safe: 'green', low: 'green', medium: 'orange', high: 'red' } as Record<string, string>)[
    risk || ''
  ] || 'gray'

const isImageUrl = (icon?: string) => {
  return Boolean(icon && (icon.startsWith('http') || icon.startsWith('/')))
}

onMounted(() => {
  void loadApps()
})
</script>

<template>
  <section class="space-y-6 p-6">
    <header>
      <h1 class="text-2xl font-semibold text-gray-900">{{ t('admin.apps.title') }}</h1>
      <p class="mt-1 text-sm text-gray-500">{{ t('admin.apps.description') }}</p>
    </header>

    <!-- 搜索栏 -->
    <div class="flex items-center justify-between gap-3">
      <a-input-search
        v-model="keyword"
        :placeholder="t('admin.apps.searchPlaceholder')"
        allow-clear
        style="max-width: 360px"
        @search="handleSearch"
      />
      <span class="text-xs text-gray-400">{{ t('admin.apps.total', { count: total }) }}</span>
    </div>

    <a-spin :loading="loading" class="block">
      <section v-if="apps.length" class="grid gap-4 xl:grid-cols-2">
        <article
          v-for="app in apps"
          :key="app.id"
          class="flex flex-col gap-3 rounded-xl border border-gray-200 bg-white p-5"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="flex items-center gap-3">
              <span
                v-if="app.icon && isImageUrl(app.icon)"
                class="inline-flex h-10 w-10 items-center justify-center overflow-hidden rounded-lg bg-gray-50"
              >
                <img :src="app.icon" :alt="app.name" class="h-full w-full object-cover" />
              </span>
              <span
                v-else-if="app.icon"
                class="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-gray-50 text-xl"
                >{{ app.icon }}</span
              >
              <span
                v-else
                class="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-gray-50 text-xl text-gray-400"
                >🤖</span
              >
              <div>
                <h2 class="text-base font-semibold text-gray-900">{{ app.name }}</h2>
                <p class="font-mono text-xs text-gray-400">{{ app.id }}</p>
              </div>
            </div>
            <a-tag v-if="app.status" :color="statusColor(app.status)" size="small">
              {{ statusLabel(app.status) }}
            </a-tag>
          </div>

          <p class="text-sm text-gray-600">
            {{ app.description || t('admin.apps.noDescription') }}
          </p>

          <dl class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <div class="flex gap-1">
              <dt class="text-gray-400">{{ t('admin.apps.accountId') }}:</dt>
              <dd class="text-gray-700">{{ app.account_id || '-' }}</dd>
            </div>
            <div class="flex gap-1">
              <dt class="text-gray-400">{{ t('admin.apps.createdAt') }}:</dt>
              <dd class="text-gray-700">{{ formatTimestamp(app.created_at) }}</dd>
            </div>
          </dl>

          <!-- 池治理字段：只读展示 + 数据所有权提示 -->
          <div class="rounded-lg bg-gray-50 p-3">
            <div class="flex flex-wrap items-center gap-2 text-xs">
              <span class="text-gray-400">{{ t('admin.apps.poolFields.primaryPool') }}:</span>
              <a-tag size="small">{{ app.agent_metadata?.primary_pool || '-' }}</a-tag>
              <span class="text-gray-400">{{ t('admin.apps.poolFields.riskLevel') }}:</span>
              <a-tag :color="riskColor(app.agent_metadata?.risk_level)" size="small">{{
                app.agent_metadata?.risk_level || '-'
              }}</a-tag>
              <span class="text-gray-400">{{ t('admin.apps.poolFields.routingPriority') }}:</span>
              <a-tag size="small">{{ app.agent_metadata?.routing_priority ?? '-' }}</a-tag>
              <span class="text-gray-400">{{ t('admin.apps.poolFields.enabled') }}:</span>
              <a-tag
                :color="app.agent_metadata?.enabled ? 'green' : 'gray'"
                size="small"
                >{{
                  app.agent_metadata?.enabled ? t('admin.apps.enabledYes') : t('admin.apps.enabledNo')
                }}</a-tag
              >
            </div>
            <p class="mt-2 text-xs text-gray-400">
              {{ t('admin.apps.poolOwnershipHint') }}
              <router-link
                :to="{ name: 'admin-agent-pool' }"
                class="font-medium text-blue-600 hover:underline"
                >{{ t('admin.apps.goToAgentPool') }}</router-link
              >
            </p>
          </div>

          <div class="mt-auto flex justify-end gap-2">
            <a-button size="small" :data-testid="`app-view-${app.id}`" @click="handleViewDetail(app)">
              {{ t('admin.apps.viewDetail') }}
            </a-button>
            <a-button
              v-if="canUpdate"
              type="primary"
              size="small"
              :data-testid="`app-edit-${app.id}`"
              @click="openEditBasic(app)"
            >
              {{ t('admin.apps.editBasic') }}
            </a-button>
          </div>
        </article>
      </section>

      <section
        v-else
        class="rounded-xl border border-dashed border-gray-300 bg-white px-6 py-12 text-center"
      >
        <h2 class="text-lg font-medium text-gray-900">{{ t('admin.apps.emptyTitle') }}</h2>
        <p class="mt-2 text-sm text-gray-500">{{ emptyDescription }}</p>
      </section>
    </a-spin>

    <div v-if="apps.length" class="flex justify-end">
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

    <!-- 编辑基本信息弹窗 -->
    <a-modal
      v-model:visible="modalVisible"
      :title="t('admin.apps.editBasicTitle')"
      :ok-loading="saving"
      :mask-closable="false"
      @ok="submitEditBasic"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item :label="t('admin.apps.appName')" field="name">
          <a-input v-model="form.name" :placeholder="t('admin.apps.namePlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('admin.apps.appDescription')" field="description">
          <a-textarea
            v-model="form.description"
            :placeholder="t('admin.apps.descriptionPlaceholder')"
            :auto-size="{ minRows: 2, maxRows: 6 }"
          />
        </a-form-item>
        <a-form-item :label="t('admin.apps.appIcon')" field="icon">
          <a-input v-model="form.icon" :placeholder="t('admin.apps.iconPlaceholder')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
