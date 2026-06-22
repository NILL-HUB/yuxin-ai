<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { listPublicShowcaseCases, type ShowcaseCase } from '@/services/showcase'
import { getErrorMessage } from '@/utils/error'
import { formatTimestampShort } from '@/utils/time-formatter'

const loading = ref(false)
const cases = ref<ShowcaseCase[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(12)
const keyword = ref('')
const selectedTag = ref('')

const availableTags = computed(() => {
  const set = new Set<string>()
  cases.value.forEach((item) => {
    item.tags?.forEach((tag) => set.add(tag))
  })
  return Array.from(set)
})

const loadCases = async () => {
  loading.value = true
  try {
    const res = await listPublicShowcaseCases({
      page: page.value,
      per_page: pageSize.value,
      tag: selectedTag.value || undefined,
      keyword: keyword.value.trim() || undefined,
    })
    cases.value = res.data.data || []
    total.value = res.data.total || 0
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, '加载案例失败'))
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  page.value = 1
  loadCases()
}

const toggleTag = (tag: string) => {
  selectedTag.value = selectedTag.value === tag ? '' : tag
  page.value = 1
  loadCases()
}

const onPageChange = (next: number) => {
  page.value = next
  loadCases()
}

const detailVisible = ref(false)
const activeCase = ref<ShowcaseCase | null>(null)
const openDetail = (item: ShowcaseCase) => {
  activeCase.value = item
  detailVisible.value = true
}

const truncate = (text: string, max = 80) => {
  const value = String(text || '').trim()
  if (value.length <= max) return value
  return `${value.slice(0, max)}...`
}

const renderStars = (rating: number) => {
  const score = Math.max(0, Math.min(5, Math.round(Number(rating) || 0)))
  return '★'.repeat(score) + '☆'.repeat(5 - score)
}

const maskContributor = (name?: string) => {
  const value = String(name || '').trim()
  if (!value) return '匿名用户'
  if (value.length <= 1) return `${value}*`
  return `${value.slice(0, 1)}***`
}

onMounted(loadCases)
</script>

<template>
  <a-spin :loading="loading" class="block h-full w-full">
    <div class="p-6 flex flex-col h-full">
      <div class="flex items-center justify-between mb-6">
        <div class="flex items-center gap-2">
          <a-avatar :size="32" class="bg-blue-700">
            <icon-bulb :size="18" />
          </a-avatar>
          <div class="text-lg font-medium text-gray-900">用户案例展示</div>
        </div>
      </div>

      <div class="flex flex-col gap-4 mb-6">
        <div
          v-if="availableTags.length > 0"
          class="flex items-center gap-2 overflow-x-auto scrollbar-hide pb-1"
        >
          <span class="text-sm text-gray-500 mr-1 whitespace-nowrap">标签</span>
          <a
            class="rounded-lg px-3 h-8 leading-8 hover:bg-gray-200 transition-all cursor-pointer whitespace-nowrap text-sm"
            :class="selectedTag === '' ? 'bg-blue-100 text-blue-700 font-medium' : 'bg-gray-100 text-gray-700'"
            @click="toggleTag('')"
          >
            全部
          </a>
          <a
            v-for="tag in availableTags"
            :key="tag"
            class="rounded-lg px-3 h-8 leading-8 hover:bg-gray-200 transition-all cursor-pointer whitespace-nowrap text-sm"
            :class="selectedTag === tag ? 'bg-blue-100 text-blue-700 font-medium' : 'bg-gray-100 text-gray-700'"
            @click="toggleTag(tag)"
          >
            {{ tag }}
          </a>
        </div>
        <a-input-search
          v-model="keyword"
          placeholder="搜索案例标题或内容"
          class="w-full sm:w-[280px] bg-white rounded-lg border-gray-300"
          @search="handleSearch"
        />
      </div>

      <div class="flex-1 overflow-y-auto overflow-x-hidden scrollbar-hide">
        <a-row :gutter="[20, 20]">
          <a-col v-for="item in cases" :key="item.id" :span="6">
            <a-card
              hoverable
              class="h-full rounded-lg flex flex-col"
              :body-style="{ padding: '16px' }"
            >
              <button
                type="button"
                class="w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded-lg flex-1"
                @click="openDetail(item)"
              >
                <div class="flex items-start justify-between gap-2 mb-2">
                  <div class="text-base font-bold text-gray-900 truncate flex-1">
                    {{ item.title || '未命名案例' }}
                  </div>
                  <div class="text-amber-500 text-sm whitespace-nowrap">
                    {{ renderStars(item.rating) }}
                  </div>
                </div>
                <p v-if="item.summary" class="text-sm text-gray-600 line-clamp-2 mb-2">
                  {{ item.summary }}
                </p>
                <div class="rounded-md bg-gray-50 px-3 py-2 mb-2">
                  <div class="text-xs text-gray-400 mb-1">提问</div>
                  <div class="text-sm text-gray-700 line-clamp-2">{{ truncate(item.query) }}</div>
                </div>
                <div class="flex items-center gap-1 flex-wrap">
                  <a-tag v-for="tag in (item.tags || []).slice(0, 3)" :key="tag" size="small">
                    {{ tag }}
                  </a-tag>
                  <a-tag v-if="(item.tags || []).length > 3" size="small">
                    +{{ item.tags.length - 3 }}
                  </a-tag>
                </div>
              </button>
              <div class="mt-3 flex items-center justify-between gap-2">
                <div class="min-w-0 truncate text-xs text-gray-400">
                  {{ maskContributor(item.contributor) }} · {{ formatTimestampShort(item.created_at) }}
                </div>
                <a-button size="mini" type="text" @click="openDetail(item)">查看详情</a-button>
              </div>
            </a-card>
          </a-col>

          <a-col v-if="!loading && cases.length === 0" :span="24">
            <a-empty description="暂无展示案例" class="py-20" />
          </a-col>
        </a-row>
      </div>

      <div
        v-if="total > pageSize"
        class="mt-4 flex justify-center"
      >
        <a-pagination
          :total="total"
          :current="page"
          :page-size="pageSize"
          show-total
          @change="onPageChange"
        />
      </div>
    </div>

    <a-modal
      v-model:visible="detailVisible"
      :title="activeCase?.title || '案例详情'"
      :width="680"
      :footer="false"
      unmount-on-close
    >
      <template v-if="activeCase">
        <div class="flex items-center gap-2 mb-4 flex-wrap">
          <div class="text-amber-500">{{ renderStars(activeCase.rating) }}</div>
          <a-tag v-for="tag in (activeCase.tags || [])" :key="tag" size="small">{{ tag }}</a-tag>
          <span class="text-xs text-gray-400 ml-auto">
            {{ maskContributor(activeCase.contributor) }} · {{ formatTimestampShort(activeCase.created_at) }}
          </span>
        </div>
        <p v-if="activeCase.summary" class="text-sm text-gray-600 mb-4">{{ activeCase.summary }}</p>
        <div class="rounded-md bg-gray-50 px-4 py-3 mb-4">
          <div class="text-xs text-gray-400 mb-1">用户提问</div>
          <div class="text-sm text-gray-800 whitespace-pre-wrap break-words">{{ activeCase.query }}</div>
        </div>
        <div class="rounded-md bg-blue-50/40 px-4 py-3">
          <div class="text-xs text-gray-400 mb-1">AI 回答</div>
          <div class="text-sm text-gray-800 whitespace-pre-wrap break-words">{{ activeCase.answer }}</div>
        </div>
      </template>
    </a-modal>
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

.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
