<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import { getWorkflowsWithPage } from '@/services/workflow'
import { listAdminWorkflows } from '@/services/admin-workflows'
import { useRealm } from '@/hooks/use-realm'
import { getErrorMessage } from '@/utils/error'

type WorkflowOption = {
  id: string
  name: string
  icon: string
  description: string
}

type PaginatorState = {
  current_page: number
  page_size: number
  total_page: number
  total_record: number
}

const props = defineProps({
  visible: { type: Boolean, default: false },
  // 当前已绑定的 workflow_id，用于在列表中高亮已选项
  selected_workflow_id: { type: String as () => string | null, default: null },
})
const emits = defineEmits(['update:visible', 'select'])
const { t } = useI18n()
const { isAdmin: isAdminContext } = useRealm()

const loading = ref(false)
const searchWord = ref('')
const workflows = ref<WorkflowOption[]>([])
const defaultPaginator: PaginatorState = {
  current_page: 1,
  page_size: 20,
  total_page: 0,
  total_record: 0,
}
const paginator = ref<PaginatorState>({ ...defaultPaginator })

const hideModal = () => emits('update:visible', false)

const loadWorkflows = async (init: boolean = false) => {
  if (loading.value) return
  if (init) {
    paginator.value = { ...defaultPaginator }
  } else if (paginator.value.current_page > paginator.value.total_page) {
    return
  }

  try {
    loading.value = true
    let list: WorkflowOption[] = []
    let respPaginator: PaginatorState = { ...defaultPaginator }

    if (isAdminContext.value) {
      const data = await listAdminWorkflows({
        search: searchWord.value.trim(),
        status: 'published',
        current_page: paginator.value.current_page,
        page_size: paginator.value.page_size,
      })
      list = data.list || []
      respPaginator = data.paginator || respPaginator
    } else {
      const resp = await getWorkflowsWithPage({
        current_page: paginator.value.current_page,
        page_size: paginator.value.page_size,
        search_word: searchWord.value.trim(),
        status: 'published',
      })
      list = resp.data.list || []
      respPaginator = resp.data.paginator || respPaginator
    }

    paginator.value = respPaginator
    if (paginator.value.current_page <= paginator.value.total_page) {
      paginator.value.current_page += 1
    }

    if (init) {
      workflows.value = list
    } else {
      workflows.value.push(...list)
    }
  } catch (error) {
    Message.error(getErrorMessage(error, t('appStudio.abilities.workflowBinding.noAvailable')))
  } finally {
    loading.value = false
  }
}

const handleSearch = async () => {
  await loadWorkflows(true)
}

const handleScroll = (event: UIEvent) => {
  const { scrollTop, scrollHeight, clientHeight } = event.target as HTMLElement
  if (scrollTop + clientHeight < scrollHeight - 10) return
  if (loading.value) return
  void loadWorkflows()
}

const handleSelect = (workflow: WorkflowOption) => {
  emits('select', workflow)
}

watch(
  () => props.visible,
  async (visible) => {
    if (!visible) {
      workflows.value = []
      searchWord.value = ''
      return
    }
    await loadWorkflows(true)
  },
  { immediate: true },
)
</script>

<template>
  <a-modal
    :visible="props.visible"
    :footer="false"
    hide-title
    :width="400"
    class="workflow-binding-modal"
    modal-class="h-[calc(100vh-32px)] right-4"
    @cancel="hideModal"
  >
    <!-- 顶部标题 -->
    <div class="flex items-center justify-between mb-6">
      <div class="text-lg font-bold text-gray-700">
        {{ t('appStudio.abilities.workflowBinding.selectTitle') }}
      </div>
      <a-button
        type="text"
        class="!text-gray-700"
        size="small"
        @click="hideModal"
      >
        <template #icon>
          <icon-close />
        </template>
      </a-button>
    </div>
    <!-- 搜索框 -->
    <div class="mb-4">
      <a-input-search
        v-model="searchWord"
        :placeholder="t('appStudio.abilities.workflowBinding.searchPlaceholder')"
        class="w-full bg-white rounded-lg"
        @search="handleSearch"
      />
    </div>
    <!-- 中间工作流列表 -->
    <div class="h-[calc(100vh-220px)] mb-4 overflow-scroll scrollbar-w-none">
      <a-spin
        :loading="loading"
        class="block h-full w-full scrollbar-w-none overflow-scroll"
        @scroll="handleScroll"
      >
        <div class="flex flex-col gap-2">
          <div
            v-for="workflow in workflows"
            :key="workflow.id"
            :class="`flex items-center gap-2 border px-3 py-2 rounded-lg cursor-pointer hover:bg-blue-50 hover:border-blue-700 ${props.selected_workflow_id === workflow.id ? 'bg-blue-50 border-blue-700' : ''}`"
            @click="handleSelect(workflow)"
          >
            <a-avatar
              :size="28"
              shape="square"
              class="flex-shrink-0 rounded"
              :image-url="workflow.icon"
            />
            <div class="flex flex-col min-w-0 flex-1">
              <div class="text-sm text-gray-700 line-clamp-1">{{ workflow.name }}</div>
              <div class="text-xs text-gray-500 line-clamp-1">{{ workflow.description }}</div>
            </div>
            <icon-check v-if="props.selected_workflow_id === workflow.id" class="text-blue-700 flex-shrink-0" />
          </div>
          <a-empty
            v-if="workflows.length === 0"
            :description="t('appStudio.abilities.workflowBinding.noAvailable')"
            class="py-20"
          />
        </div>
        <a-row v-if="paginator.total_page >= 2">
          <a-col v-if="loading" :span="24" class="!text-center">
            <a-space class="my-4">
              <a-spin />
              <div class="text-gray-400">{{ t('appStudio.list.loading') }}</div>
            </a-space>
          </a-col>
          <a-col v-else-if="paginator.current_page > paginator.total_page" :span="24" class="!text-center">
            <div class="text-gray-400 my-4">{{ t('appStudio.list.loadedAll') }}</div>
          </a-col>
        </a-row>
      </a-spin>
    </div>
  </a-modal>
</template>

<style>
.workflow-binding-modal {
  .arco-modal-wrapper {
    @apply text-right;
  }
}
</style>
