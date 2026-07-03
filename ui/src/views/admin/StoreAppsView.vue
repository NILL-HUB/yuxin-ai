<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  listAdminApps,
  offlineAdminApp,
  updateAdminAppIsPublic,
  type AdminAppRecord,
} from '@/services/admin-apps'
import { useAdminStore } from '@/stores/admin'
import { getErrorMessage } from '@/utils/error'

type AppPaginator = {
  total_record: number
  total_page: number
  current_page: number
  page_size: number
}

/**
 * 资源运营-应用商店上下架管理页，负责公共商店中应用资源的上架/下架操作。
 */
const adminStore = useAdminStore()
const { t } = useI18n()

const loading = ref(false)
const apps = ref<AdminAppRecord[]>([])
const paginator = ref<AppPaginator>({
  total_record: 0,
  total_page: 0,
  current_page: 1,
  page_size: 20,
})
const search = ref('')

const canUpdate = computed(() => adminStore.hasPermission('app:update'))
const hasActiveFilters = computed(() => Boolean(search.value))
const emptyDescription = computed(() => {
  return hasActiveFilters.value
    ? t('admin.storeOps.emptyFiltered')
    : t('admin.storeOps.empty')
})

/**
 * 拉取后台应用列表并同步分页状态。
 */
const loadApps = async () => {
  loading.value = true
  try {
    const result = await listAdminApps({
      current_page: paginator.value.current_page,
      page_size: paginator.value.page_size,
      search: search.value,
    })
    apps.value = result.list
    paginator.value = result.paginator
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.storeOps.loadFailed')))
  } finally {
    loading.value = false
  }
}

/**
 * 搜索条件变化后刷新列表，并回到第一页。
 */
const handleSearch = async () => {
  paginator.value.current_page = 1
  await loadApps()
}

/**
 * 切换应用公开状态（上架/下架），并在成功后刷新当前列表。
 */
const handleTogglePublic = async (app: AdminAppRecord) => {
  try {
    await updateAdminAppIsPublic(app.id, !app.is_public)
    Message.success(
      app.is_public ? t('admin.storeOps.unpublishSuccess') : t('admin.storeOps.publishSuccess'),
    )
    await loadApps()
  } catch (error) {
    Message.error(
      getErrorMessage(
        error,
        app.is_public ? t('admin.storeOps.unpublishFailed') : t('admin.storeOps.publishFailed'),
      ),
    )
  }
}

/**
 * 强制下架应用，并在成功后刷新当前列表。
 */
const handleOffline = async (app: AdminAppRecord) => {
  try {
    await offlineAdminApp(app.id)
    Message.success(t('admin.storeOps.offlineSuccess', { name: app.name }))
    await loadApps()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.storeOps.offlineFailed')))
  }
}

const visibilityLabel = (app: AdminAppRecord) => {
  return app.is_public
    ? t('admin.storeOps.visibility.public')
    : t('admin.storeOps.visibility.private')
}

const toggleLabel = (app: AdminAppRecord) => {
  return app.is_public
    ? t('admin.storeOps.actions.unpublish')
    : t('admin.storeOps.actions.publish')
}

/**
 * 在新标签页中以用户视角预览公共应用商店。
 */
const handlePreviewStore = () => {
  window.open('/store/public-apps', '_blank')
}

onMounted(() => {
  void loadApps()
})
</script>

<template>
  <section class="space-y-6">
    <header class="flex items-start justify-between gap-4">
      <div>
        <h1 class="text-2xl font-semibold text-slate-900">{{ t('admin.storeOps.appsTitle') }}</h1>
        <p class="mt-1 text-sm text-slate-500">{{ t('admin.storeOps.appsDescription') }}</p>
      </div>
      <a-tooltip :content="t('admin.storeOps.previewStoreTip')" position="bl">
        <a-button @click="handlePreviewStore">
          <template #icon>
            <icon-eye />
          </template>
          {{ t('admin.storeOps.previewStore') }}
        </a-button>
      </a-tooltip>
    </header>

    <a-alert type="info" :show-icon="true">
      {{ t('admin.storeOps.opsHint') }}
    </a-alert>

    <div
      class="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm lg:flex-row lg:items-center"
    >
      <a-input
        :model-value="search"
        :placeholder="t('admin.storeOps.searchPlaceholder')"
        allow-clear
        @update:model-value="search = String($event ?? '')"
        @press-enter="handleSearch"
      />
      <a-button type="primary" :loading="loading" @click="loadApps">
        {{ t('common.actions.refresh') }}
      </a-button>
    </div>

    <section v-if="apps.length" class="grid gap-4 xl:grid-cols-2">
      <article
        v-for="app in apps"
        :key="app.id"
        class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <div class="flex items-start justify-between gap-4">
          <div class="flex min-w-0 items-center gap-3">
            <a-avatar :size="40" shape="square" :image-url="app.icon" />
            <div class="min-w-0">
              <h3 class="truncate text-lg font-semibold text-slate-900">{{ app.name }}</h3>
              <p class="mt-1 line-clamp-2 text-sm text-slate-600">
                {{ app.description || t('admin.workflowsAdmin.noDescription') }}
              </p>
            </div>
          </div>
          <div class="flex shrink-0 flex-col items-end gap-2 text-xs text-slate-500">
            <span class="rounded-full bg-slate-100 px-2 py-1">{{ visibilityLabel(app) }}</span>
          </div>
        </div>

        <div class="mt-4 flex flex-wrap gap-2">
          <a-button
            v-if="canUpdate"
            :data-testid="`app-visibility-${app.id}`"
            @click="handleTogglePublic(app)"
          >
            {{ toggleLabel(app) }}
          </a-button>
          <a-button
            v-if="canUpdate"
            status="danger"
            :data-testid="`app-offline-${app.id}`"
            @click="handleOffline(app)"
          >
            {{ t('admin.storeOps.actions.offline') }}
          </a-button>
        </div>
      </article>
    </section>

    <section
      v-else
      class="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center"
    >
      <h2 class="text-lg font-medium text-slate-900">{{ t('admin.storeOps.emptyTitle') }}</h2>
      <p class="mt-2 text-sm text-slate-500">{{ emptyDescription }}</p>
    </section>

    <footer class="text-xs text-slate-400">
      {{ t('admin.storeOps.total', { count: paginator.total_record }) }}
    </footer>
  </section>
</template>
