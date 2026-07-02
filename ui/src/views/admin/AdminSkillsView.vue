<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import type { GetSkillsWithPageRequest, SkillPackage } from '@/models/skill'
import { listAdminSkills } from '@/services/admin-skills'
import { getErrorMessage } from '@/utils/error'

type SkillPaginator = {
  total_record: number
  total_page: number
  current_page: number
  page_size: number
}

/**
 * 后台 Skills 管理页，负责展示平台技能目录列表。
 */
const { t } = useI18n()

const loading = ref(false)
const skills = ref<SkillPackage[]>([])
const paginator = ref<SkillPaginator>({
  total_record: 0,
  total_page: 0,
  current_page: 1,
  page_size: 20,
})
const filters = ref<GetSkillsWithPageRequest>({
  search_word: '',
  current_page: 1,
  page_size: 20,
  category: '',
})

const hasActiveFilters = computed(() => Boolean(filters.value.search_word?.trim()))
const emptyDescription = computed(() => {
  return hasActiveFilters.value
    ? t('admin.skillsAdmin.emptyFiltered')
    : t('admin.skillsAdmin.empty')
})

/**
 * 拉取后台 Skills 列表并同步分页信息。
 */
const loadSkills = async () => {
  loading.value = true
  try {
    const result = await listAdminSkills({ ...filters.value })
    skills.value = result.list || []
    paginator.value = result.paginator
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.skillsAdmin.loadFailed')))
  } finally {
    loading.value = false
  }
}

/**
 * 触发搜索并重置到第一页。
 */
const handleSearch = async () => {
  filters.value.current_page = 1
  await loadSkills()
}

onMounted(() => {
  void loadSkills()
})
</script>

<template>
  <section class="space-y-6">
    <header>
      <h1 class="text-2xl font-semibold text-slate-900">{{ t('admin.skillsAdmin.title') }}</h1>
      <p class="mt-1 text-sm text-slate-500">{{ t('admin.skillsAdmin.description') }}</p>
    </header>

    <section class="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4">
      <a-input
        v-model="filters.search_word"
        class="max-w-xl flex-1 min-w-[260px]"
        :placeholder="t('admin.skillsAdmin.searchPlaceholder')"
        @press-enter="handleSearch"
      />
      <a-button type="primary" :loading="loading" @click="handleSearch">
        {{ t('common.actions.search') }}
      </a-button>
      <a-button :loading="loading" @click="loadSkills">
        {{ t('common.actions.refresh') }}
      </a-button>
    </section>

    <section v-if="skills.length" class="grid gap-4 xl:grid-cols-2">
      <article
        v-for="skill in skills"
        :key="skill.id"
        class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-100"
      >
        <div class="min-w-0">
          <h2 class="truncate text-lg font-semibold text-slate-900">{{ skill.label || skill.name }}</h2>
          <p class="mt-2 text-sm text-slate-500">{{ skill.description || '-' }}</p>
        </div>

        <dl class="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <div>
            <dt class="text-slate-400">{{ t('admin.skillsAdmin.sourceKey') }}</dt>
            <dd class="mt-1 break-all text-slate-700">{{ skill.source_key }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">{{ t('admin.skillsAdmin.category') }}</dt>
            <dd class="mt-1 text-slate-700">{{ skill.category || '-' }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">{{ t('admin.skillsAdmin.executorType') }}</dt>
            <dd class="mt-1 text-slate-700">{{ skill.executor_type }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">{{ t('admin.skillsAdmin.toolCount') }}</dt>
            <dd class="mt-1 text-slate-700">{{ skill.tool_count }}</dd>
          </div>
        </dl>
      </article>
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
  </section>
</template>
