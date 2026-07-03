<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { apiPrefix } from '@/config'
import CardGridSkeleton from '@/components/skeletons/CardGridSkeleton.vue'
import ResourceCardDescription from '@/components/ResourceCardDescription.vue'
import { useMarkdownRenderer } from '@/hooks/use-markdown-renderer'
import { getErrorMessage } from '@/utils/error'
import 'github-markdown-css'
import type { GetSkillsWithPageRequest, SkillPackage } from '@/models/skill'
import { listAdminSkills } from '@/services/admin-skills'
import { getSkillCategoryDisplayName } from '@/utils/store-display'

type SkillPaginator = {
  total_record: number
  total_page: number
  current_page: number
  page_size: number
}

/**
 * 后台 Skills 管理页，负责展示平台技能目录列表（只读）。
 * UI 与 Skills 商店保持一致：响应式卡片网格 + 分类筛选 + 详情抽屉。
 */
const PAGE_SIZE = 100

const router = useRouter()
const { t, locale } = useI18n()

const loading = ref(false)
const skills = ref<SkillPackage[]>([])
const categorySet = ref<Set<string>>(new Set())
const selectedCategory = ref('all')
const searchWord = ref('')
const paginator = ref<SkillPaginator>({
  total_record: 0,
  total_page: 0,
  current_page: 1,
  page_size: PAGE_SIZE,
})

const showDetailVisible = ref(false)
const activeSkill = ref<SkillPackage | null>(null)
const { renderMarkdown } = useMarkdownRenderer()

const avatarPalettes = [
  ['#334155', '#0f172a'],
  ['#0369a1', '#1d4ed8'],
  ['#047857', '#0f766e'],
  ['#c2410c', '#d97706'],
  ['#be123c', '#e11d48'],
  ['#0f766e', '#14b8a6'],
]

const categories = computed(() => Array.from(categorySet.value))

const hasActiveFilters = computed(
  () => Boolean(searchWord.value.trim()) || selectedCategory.value !== 'all',
)
const emptyDescription = computed(() =>
  hasActiveFilters.value ? t('admin.skillsAdmin.emptyFiltered') : t('admin.skillsAdmin.empty'),
)

const normalizeIconUrl = (icon: string = '') => {
  if (!icon) return ''
  if (icon.startsWith('data:') || /^https?:\/\//.test(icon)) return icon
  const fallbackOrigin = globalThis.location?.origin ?? 'http://localhost'
  const apiUrl = new URL(apiPrefix, fallbackOrigin)
  const basePath = apiUrl.pathname.replace(/\/+$/, '')
  let path = icon.startsWith('/') ? icon : `/${icon}`

  if (path.startsWith('/api/') && !basePath.startsWith('/api')) {
    path = path.replace(/^\/api/, '')
  }

  if (basePath && basePath !== '/' && !path.startsWith(`${basePath}/`)) {
    if (path.startsWith('/api/')) {
      path = path.replace(/^\/api/, '')
    }
    return `${apiUrl.origin}${basePath}${path}`
  }

  return `${apiUrl.origin}${path}`
}

/**
 * 拉取后台 Skills 列表并同步分页信息，同时累计分类用于筛选栏。
 */
const loadSkills = async () => {
  loading.value = true
  try {
    const params: GetSkillsWithPageRequest = {
      search_word: searchWord.value.trim(),
      current_page: 1,
      page_size: PAGE_SIZE,
      category: selectedCategory.value === 'all' ? '' : selectedCategory.value,
    }
    const result = await listAdminSkills(params)
    skills.value = result.list || []
    paginator.value = result.paginator
    const next = new Set(categorySet.value)
    skills.value.forEach((skill) => {
      if (skill.category) next.add(skill.category)
    })
    categorySet.value = next
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.skillsAdmin.loadFailed')))
  } finally {
    loading.value = false
  }
}

const handleSearch = async () => {
  await loadSkills()
}

const handleCategoryChange = async (category: string) => {
  selectedCategory.value = category
  await loadSkills()
}

/**
 * 跳转到 Skills 商店浏览页（Skill 包的上传与删除暂未在后台开放）。
 */
const handleBrowseStore = async () => {
  await router.push({ name: 'admin-store-skills' })
}

const handleCardClick = (skill: SkillPackage) => {
  activeSkill.value = skill
  showDetailVisible.value = true
}

const hashString = (value: string) => {
  let hash = 0
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 33 + value.charCodeAt(i)) >>> 0
  }
  return hash
}

const getSkillAvatarText = (skill: SkillPackage) => {
  const source = (skill.label || skill.name || skill.source_key || 'SK').trim()
  const latinParts = source.match(/[A-Za-z0-9]+/g)
  if (latinParts && latinParts.length > 0) {
    return latinParts
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join('')
  }
  const chineseParts = source.match(/[\u4e00-\u9fff]/g)
  if (chineseParts && chineseParts.length > 0) {
    return chineseParts.slice(0, 2).join('')
  }
  return source.slice(0, 2).toUpperCase()
}

const getSkillAvatarStyle = (skill: SkillPackage) => {
  const palette =
    avatarPalettes[
      hashString(`${skill.category}:${skill.source_key}:${skill.label}`) % avatarPalettes.length
    ]
  return {
    background: `linear-gradient(135deg, ${palette[0]} 0%, ${palette[1]} 100%)`,
    boxShadow: 'inset 0 1px 0 rgba(255, 255, 255, 0.15)',
  }
}

const getCategoryButtonClass = (active: boolean) =>
  ['skills-category-btn', active ? 'skills-category-btn-active' : 'skills-category-btn-inactive'].join(
    ' ',
  )

const getCategoryLabel = (category: string) =>
  getSkillCategoryDisplayName(category, locale.value as 'zh-CN' | 'en-US')

const getExecutorTypeLabel = (value: string) => {
  const normalized = String(value || '').trim()
  if (!normalized) return ''
  if (normalized === 'scf') return t('admin.skillsAdmin.executorTypes.scf')
  if (normalized === 'tool') return t('admin.skillsAdmin.executorTypes.tool')
  if (normalized === 'prompt') return t('admin.skillsAdmin.executorTypes.prompt')
  return normalized
}

const detailMarkdown = computed(() =>
  renderMarkdown(activeSkill.value?.readme || activeSkill.value?.description || t('admin.skillsAdmin.noBody')),
)

onMounted(() => {
  void loadSkills()
})
</script>

<template>
  <section class="space-y-5">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold text-slate-900">{{ t('admin.skillsAdmin.title') }}</h1>
        <p class="mt-1 text-sm text-slate-500">{{ t('admin.skillsAdmin.description') }}</p>
      </div>
      <a-button type="primary" @click="handleBrowseStore">
        {{ t('admin.skillsAdmin.browseStore') }}
      </a-button>
    </header>

    <a-alert type="info" :show-icon="true">
      {{ t('admin.skillsAdmin.manageHint') }}
    </a-alert>

    <section
      class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4"
    >
      <div class="flex flex-wrap items-center gap-2">
        <a-button
          type="text"
          :class="getCategoryButtonClass(selectedCategory === 'all')"
          @click="handleCategoryChange('all')"
        >
          {{ t('admin.skillsAdmin.all') }}
        </a-button>
        <a-button
          v-for="category in categories"
          :key="category"
          type="text"
          :class="getCategoryButtonClass(selectedCategory === category)"
          @click="handleCategoryChange(category)"
        >
          {{ getCategoryLabel(category) }}
        </a-button>
      </div>

      <div class="flex items-center gap-2">
        <a-input
          v-model="searchWord"
          class="w-full sm:w-[260px]"
          :placeholder="t('admin.skillsAdmin.searchPlaceholder')"
          allow-clear
          @press-enter="handleSearch"
          @clear="handleSearch"
        />
        <a-button type="primary" :loading="loading" @click="handleSearch">
          {{ t('common.actions.search') }}
        </a-button>
        <a-button :loading="loading" @click="loadSkills">
          {{ t('common.actions.refresh') }}
        </a-button>
      </div>
    </section>

    <card-grid-skeleton v-if="loading && skills.length === 0" :count="8" />

    <section v-else-if="skills.length" class="overflow-x-hidden">
      <a-row :gutter="[16, 16]">
        <a-col
          v-for="skill in skills"
          :key="skill.id"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
          :xl="6"
        >
          <a-card
            hoverable
            class="cursor-pointer rounded-lg h-full overflow-hidden"
            :body-style="{ padding: '10px' }"
            @click="handleCardClick(skill)"
          >
            <div class="flex items-start gap-2.5 mb-2">
              <a-avatar
                :size="34"
                shape="square"
                class="shrink-0 overflow-hidden"
                :style="skill.icon ? { backgroundColor: '#f3f4f6' } : getSkillAvatarStyle(skill)"
              >
                <img
                  v-if="skill.icon"
                  :src="normalizeIconUrl(skill.icon)"
                  :alt="skill.label"
                  class="w-full h-full object-cover"
                />
                <span v-else class="text-white font-semibold text-[12px] tracking-wide">
                  {{ getSkillAvatarText(skill) }}
                </span>
              </a-avatar>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-1.5 min-w-0">
                  <div class="text-sm font-bold text-gray-900 truncate">{{ skill.label }}</div>
                </div>
                <div class="text-[11px] text-gray-500 line-clamp-1">
                  {{ skill.source_key }}
                  <template v-if="skill.tool_count > 0">
                    · {{ t('admin.skillsAdmin.toolCountBadge', { count: skill.tool_count }) }}
                  </template>
                </div>
              </div>
            </div>

            <resource-card-description :text="skill.description" />

            <div class="flex flex-wrap items-center gap-1.5 mt-2.5">
              <a-tag size="small" color="gray">{{ getCategoryLabel(skill.category) }}</a-tag>
              <a-tag size="small" :color="skill.executor_type === 'scf' ? 'green' : 'gray'">
                {{ getExecutorTypeLabel(skill.executor_type) }}
              </a-tag>
            </div>

            <div class="flex items-center gap-1.5 mt-2.5">
              <a-avatar :size="16" class="bg-blue-700">
                <icon-file :size="10" />
              </a-avatar>
              <div class="text-[11px] text-gray-400">
                <template v-if="skill.tool_count > 0">
                  {{ t('admin.skillsAdmin.toolCountBadge', { count: skill.tool_count }) }}
                </template>
                <template v-else>{{ t('admin.skillsAdmin.promptOnly') }}</template>
              </div>
            </div>
          </a-card>
        </a-col>
      </a-row>
    </section>

    <section
      v-else
      class="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center"
    >
      <h2 class="text-lg font-medium text-slate-900">{{ t('admin.skillsAdmin.emptyTitle') }}</h2>
      <p class="mt-2 text-sm text-slate-500">{{ emptyDescription }}</p>
    </section>

    <footer class="text-xs text-slate-400">
      {{ t('admin.skillsAdmin.total', { count: paginator.total_record }) }}
    </footer>

    <a-drawer
      :visible="showDetailVisible"
      :width="560"
      :footer="false"
      :title="t('admin.skillsAdmin.detailTitle')"
      :drawer-style="{ background: '#F9FAFB' }"
      @cancel="showDetailVisible = false"
    >
      <div v-if="activeSkill" class="flex flex-col gap-4">
        <div class="flex items-start gap-3">
          <a-avatar
            :size="40"
            shape="square"
            class="overflow-hidden"
            :style="
              activeSkill.icon ? { backgroundColor: '#f3f4f6' } : getSkillAvatarStyle(activeSkill)
            "
          >
            <img
              v-if="activeSkill.icon"
              :src="normalizeIconUrl(activeSkill.icon)"
              :alt="activeSkill.label"
              class="w-full h-full object-cover"
            />
            <span v-else class="text-white font-semibold text-[12px] tracking-wide">
              {{ getSkillAvatarText(activeSkill) }}
            </span>
          </a-avatar>
          <div class="flex-1 min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <div class="text-sm font-bold text-gray-900">{{ activeSkill.label }}</div>
              <a-tag size="small" color="gray">{{ getCategoryLabel(activeSkill.category) }}</a-tag>
            </div>
            <div class="text-[11px] text-gray-500 mt-1">
              {{ activeSkill.source_key }}
              <template v-if="activeSkill.tool_count > 0">
                · {{ t('admin.skillsAdmin.toolCountBadge', { count: activeSkill.tool_count }) }}
              </template>
            </div>
          </div>
        </div>

        <div class="rounded-lg bg-white p-3.5">
          <div class="markdown-body skill-markdown" v-html="detailMarkdown" />
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div class="rounded-lg bg-white p-3">
            <div class="text-xs text-gray-500 mb-1">{{ t('admin.skillsAdmin.category') }}</div>
            <div class="text-sm text-gray-800">
              {{ getCategoryLabel(activeSkill.category) || '-' }}
            </div>
          </div>
          <div class="rounded-lg bg-white p-3">
            <div class="text-xs text-gray-500 mb-1">{{ t('admin.skillsAdmin.executorType') }}</div>
            <div class="text-sm text-gray-800">
              {{ getExecutorTypeLabel(activeSkill.executor_type) || '-' }}
            </div>
          </div>
          <div class="rounded-lg bg-white p-3">
            <div class="text-xs text-gray-500 mb-1">{{ t('admin.skillsAdmin.sourceKey') }}</div>
            <div class="mt-1 break-all text-sm text-gray-800">{{ activeSkill.source_key }}</div>
          </div>
          <div class="rounded-lg bg-white p-3">
            <div class="text-xs text-gray-500 mb-1">{{ t('admin.skillsAdmin.toolCountLabel') }}</div>
            <div class="text-sm text-gray-800">{{ activeSkill.tool_count }}</div>
          </div>
        </div>

        <div v-if="activeSkill.tools && activeSkill.tools.length > 0">
          <div class="text-sm font-bold text-gray-700 mb-2">
            {{ t('admin.skillsAdmin.toolsTitle') }}
          </div>
          <div class="space-y-2">
            <a-card
              v-for="tool in activeSkill.tools"
              :key="tool.name"
              class="rounded-lg"
              :body-style="{ padding: '12px' }"
            >
              <div class="font-semibold text-gray-900">{{ tool.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ tool.description }}</div>
            </a-card>
          </div>
        </div>
      </div>
    </a-drawer>
  </section>
</template>

<style scoped>
.skill-markdown :deep(h1),
.skill-markdown :deep(h2),
.skill-markdown :deep(h3),
.skill-markdown :deep(h4),
.skill-markdown :deep(h5),
.skill-markdown :deep(h6) {
  margin-top: 1rem;
}

.skill-markdown :deep(p):first-child {
  margin-top: 0;
}

.skill-markdown :deep(ul),
.skill-markdown :deep(ol) {
  padding-left: 1.25rem;
}

.skills-category-btn {
  height: 32px;
  border-radius: 10px;
  padding: 0 12px;
  font-size: 12px;
}

.skills-category-btn-active {
  background: #eef2f7 !important;
  color: #111827 !important;
}

.skills-category-btn-inactive {
  color: #4b5563 !important;
}

.skills-category-btn:hover {
  background: #f3f4f6 !important;
}

.skills-category-btn-active:hover {
  background: #e5e7eb !important;
}
</style>
