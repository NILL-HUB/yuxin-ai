<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import {
  getPublicApps,
  getAppTags,
  forkPublicApp,
  type PublicApp,
  type AppTag
} from '@/services/public-app'
import { getErrorMessage } from '@/utils/error'
import { isCredentialLoggedIn } from '@/utils/auth'
import { AUTH_REQUIRED_EVENT } from '@/utils/request'
import { useCredentialStore } from '@/stores/credential'
import { formatTimestampShort } from '@/utils/time-formatter'
import ResourceCardDescription from '@/components/ResourceCardDescription.vue'
import { getPublicAppTagDisplayName } from '@/utils/public-app-tag-display'

const route = useRoute()
const router = useRouter()
const credentialStore = useCredentialStore()
const { t, locale } = useI18n()
const loading = ref(false)
const apps = ref<PublicApp[]>([])
const tags = ref<AppTag[]>([])
const selectedTags = ref<string[]>([])
const searchWord = ref('')
const page = ref(1)
const pageSize = ref(20)
const hasMore = ref(true)
const forkingAppId = ref('')

const isLoggedIn = computed(() => isCredentialLoggedIn(credentialStore.credential))

const openLoginModal = () => {
  if (typeof window === 'undefined') return
  window.dispatchEvent(
    new CustomEvent(AUTH_REQUIRED_EVENT, {
      detail: { redirect: route.fullPath },
    }),
  )
}

const handleFork = async (app: PublicApp, event: Event) => {
  event.stopPropagation()
  if (!isLoggedIn.value) {
    openLoginModal()
    return
  }
  if (app.is_forked || forkingAppId.value) return
  forkingAppId.value = app.id
  try {
    await forkPublicApp(app.id)
    app.is_forked = true
    Message.success(t('publicApps.list.forkSuccess', { name: app.name }))
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('publicApps.list.actionFailed')))
  } finally {
    forkingAppId.value = ''
  }
}

const loadApps = async () => {
  if (loading.value) return
  if (!hasMore.value && page.value > 1) return

  loading.value = true
  try {
    const res = await getPublicApps({
      current_page: page.value,
      page_size: pageSize.value,
      tags: selectedTags.value.join(','),
      search_word: searchWord.value
    })
    const list = res.data.list
    if (page.value === 1) {
      apps.value = list
    } else {
      apps.value.push(...list)
    }
    hasMore.value = page.value < res.data.paginator.total_page
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('publicApps.list.loadAppsFailed')))
  } finally {
    loading.value = false
  }
}

const loadTags = async () => {
  try {
    const res = await getAppTags()
    tags.value = res.data.tags
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('publicApps.list.loadTagsFailed')))
  }
}

const handlePreview = (app: PublicApp) => {
  router.push({ name: 'store-public-apps-preview', params: { app_id: app.id } })
}

const toggleTag = (tagId: string) => {
  const index = selectedTags.value.indexOf(tagId)
  if (index > -1) {
    selectedTags.value.splice(index, 1)
  } else {
    selectedTags.value.push(tagId)
  }
  page.value = 1
  hasMore.value = true
  loadApps()
}

const handleSearch = () => {
  page.value = 1
  hasMore.value = true
  loadApps()
}

const handleScroll = (event: Event) => {
  const target = event.target as HTMLElement | null
  if (!target) return
  const { scrollTop, scrollHeight, clientHeight } = target
  if (scrollTop + clientHeight >= scrollHeight - 10) {
    if (loading.value || !hasMore.value) return
    page.value += 1
    void loadApps()
  }
}

const getDisplayTags = (appTags: string[]) => {
  if (!appTags || appTags.length === 0) return []
  return appTags.slice(0, 3)
}

const getTagName = (tagId: string) => {
  const tag = tags.value.find(t => t.id === tagId)
  if (!tag) return tagId
  return getPublicAppTagDisplayName(tag, locale.value as 'zh-CN' | 'en-US')
}

const getExtraTagCount = (appTags: string[]) => {
  if (!appTags || appTags.length <= 3) return 0
  return appTags.length - 3
}

const getExtraTagNames = (appTags: string[]) => {
  if (!appTags || appTags.length <= 3) return []
  return appTags.slice(3).map(tagId => getTagName(tagId))
}

onMounted(() => {
  loadTags()
  loadApps()
})
</script>

<template>
  <a-spin :loading="loading" class="block h-full w-full">
    <div class="p-6 flex flex-col h-full">
      <div class="flex items-center justify-between mb-6">
        <div class="flex items-center gap-2">
          <a-avatar :size="32" class="bg-brand">
            <icon-apps :size="18" />
          </a-avatar>
          <div class="text-lg font-medium text-text">{{ t('publicApps.list.title') }}</div>
        </div>
      </div>

      <div class="flex flex-col gap-4 mb-6">
        <div class="flex items-center gap-2 overflow-x-auto scrollbar-hide pb-1">
          <span class="text-sm text-muted mr-1 whitespace-nowrap">
            {{ t('publicApps.list.tags') }}
          </span>
          <a
            v-for="tag in tags"
            :key="tag.id"
            class="rounded-lg px-3 h-8 leading-8 hover:bg-border-strong transition-all cursor-pointer whitespace-nowrap text-sm"
            :class="selectedTags.includes(tag.id) ? 'bg-brand-soft text-brand-text font-medium' : 'bg-surface-2 text-text-2'"
            @click="toggleTag(tag.id)"
          >
            {{ getTagName(tag.id) }}
          </a>
        </div>
        <a-input-search
          v-model="searchWord"
          :placeholder="t('publicApps.list.searchPlaceholder')"
          class="w-full sm:w-[240px] bg-surface rounded-lg border-border-c"
          @search="handleSearch"
        />
      </div>

      <div class="flex-1 overflow-y-auto overflow-x-hidden scrollbar-hide" @scroll="handleScroll">
        <a-row :gutter="[20, 20]">
          <a-col v-for="app in apps" :key="app.id" :xs="24" :sm="12" :md="8" :lg="6">
            <a-card hoverable class="h-full rounded-lg flex flex-col" :body-style="{ padding: '16px' }">
              <button type="button" class="w-full flex-1 text-left focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-brand rounded-lg" @click="handlePreview(app)">
                <!-- 顶部应用名称和标签 -->
                <div class="flex items-center gap-3 mb-3">
                  <a-avatar :size="40" shape="square" :image-url="app.icon" />
                  <div class="flex-1 min-w-0">
                    <div class="text-base font-bold text-text truncate">{{ app.name }}</div>
                    <div class="flex items-center gap-1 flex-wrap">
                      <a-tag v-for="tag in getDisplayTags(app.tags)" :key="tag" size="small">
                        {{ getTagName(tag) }}
                      </a-tag>
                      <a-tag v-if="getExtraTagCount(app.tags) > 0" size="small" class="cursor-help" :title="getExtraTagNames(app.tags).join(', ')">
                        +{{ getExtraTagCount(app.tags) }}
                      </a-tag>
                    </div>
                  </div>
                </div>

                <!-- 应用描述 -->
                <resource-card-description :text="app.description" />
              </button>

              <!-- 发布者与操作 -->
              <div class="mt-3 flex items-center gap-2 border-t border-border-c pt-3">
                <a-avatar :size="18" :image-url="app.creator_avatar" />
                <div class="min-w-0 flex-1 truncate text-xs text-muted">
                  {{ app.creator_name }} · {{ t('publicApps.list.publishedAt', { time: formatTimestampShort(app.published_at) }) }}
                </div>
                <a-button
                  size="mini"
                  :loading="forkingAppId === app.id"
                  :disabled="Boolean(app.is_forked)"
                  @click.stop="handleFork(app, $event)"
                >
                  {{
                    app.is_forked
                      ? t('publicApps.list.addedToSpace')
                      : isLoggedIn
                        ? t('publicApps.list.addToSpace')
                        : t('publicApps.list.loginToAdd')
                  }}
                </a-button>
              </div>
            </a-card>
          </a-col>

          <a-col v-if="apps.length === 0" :span="24">
            <a-empty :description="t('publicApps.list.empty')" class="py-20" />
          </a-col>
        </a-row>

        <div v-if="apps.length > 0" class="py-4 text-center">
          <a-space v-if="loading">
            <a-spin />
            <div class="text-muted">{{ t('publicApps.list.loading') }}</div>
          </a-space>
          <div v-else-if="!hasMore" class="text-muted">{{ t('publicApps.list.loadedAll') }}</div>
        </div>
      </div>
    </div>
  </a-spin>
</template>

<style scoped>
.scrollbar-hide {
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.scrollbar-hide::-webkit-scrollbar {
  display: none;
}
</style>
