<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import CardGridSkeleton from '@/components/skeletons/CardGridSkeleton.vue'
import ResourceCardDescription from '@/components/ResourceCardDescription.vue'
import { useAdminStore } from '@/stores/admin'
import { getErrorMessage } from '@/utils/error'
import { formatTimestampShort } from '@/utils/time-formatter'
import type {
  CreateSystemKnowledgeRequest,
  SystemKnowledgeRecord,
  UpdateSystemKnowledgeRequest,
} from '@/models/admin-system-knowledge'
import {
  createSystemKnowledge,
  deleteSystemKnowledge,
  listSystemKnowledge,
  updateSystemKnowledge,
} from '@/services/admin-system-knowledge'
import {
  listPromptTemplates,
  updatePromptTemplate,
  resetPromptTemplate,
  type PromptTemplateItem,
} from '@/services/admin-prompt-template'

/**
 * 后台系统知识库管理页。
 * 展示平台系统知识库列表，支持创建、编辑、删除，并按可见范围（private/internal/public）分类。
 * UI 与 AdminSkillsView/AdminMcpView 保持一致：响应式卡片网格 + 顶部搜索 + 分页。
 *
 * 第二个页签融合了 Prompt 模板管理（指挥官等系统 prompt），
 * 与知识库共享页面入口、权限和布局风格，避免新开独立板块。
 */
const { t } = useI18n()
const adminStore = useAdminStore()

// 写权限校验
const canWrite = computed(() => adminStore.hasPermission('system_knowledge:write'))

// 当前激活的页签：knowledge | prompts
const activeTab = ref<'knowledge' | 'prompts'>('knowledge')

// ==================== 知识库页签 ====================
const loading = ref(false)
const submitting = ref(false)
// 服务端分页：records 仅保存当前页数据
const records = ref<SystemKnowledgeRecord[]>([])
const searchWord = ref('')
const currentPage = ref(1)
const pageSize = ref(20)
// 服务端返回的总记录数（驱动分页器）
const totalRecord = ref(0)

// 创建/编辑弹窗状态
const modalVisible = ref(false)
const modalMode = ref<'create' | 'edit'>('create')
const editingId = ref<string>('')
const formModel = ref<{ name: string; description: string; visibility_scope: string }>({
  name: '',
  description: '',
  visibility_scope: 'internal',
})

// 可见范围下拉选项
const visibilityOptions = computed(() => [
  { value: 'private', label: t('admin.systemKnowledge.visibilityScopes.private') },
  { value: 'internal', label: t('admin.systemKnowledge.visibilityScopes.internal') },
  { value: 'public', label: t('admin.systemKnowledge.visibilityScopes.public') },
])

// 服务端分页+搜索：不再在前端做切片/过滤，所有过滤与分页均由后端返回
const hasActiveFilters = computed(() => Boolean(searchWord.value.trim()))
const emptyDescription = computed(() =>
  hasActiveFilters.value
    ? t('admin.systemKnowledge.emptyFiltered')
    : t('admin.systemKnowledge.empty'),
)

// 搜索关键词变化时仅重置到第一页，实际查询由 handleSearch（按钮/回车/清除）触发
watch(searchWord, () => {
  currentPage.value = 1
})

/**
 * 根据可见范围返回标签颜色。
 */
const getVisibilityTagColor = (scope?: string) => {
  if (scope === 'private') return 'gray'
  if (scope === 'public') return 'green'
  return 'arcoblue'
}

/**
 * 根据可见范围返回本地化文案。
 */
const getVisibilityLabel = (scope?: string) => {
  if (scope === 'private') return t('admin.systemKnowledge.visibilityScopes.private')
  if (scope === 'public') return t('admin.systemKnowledge.visibilityScopes.public')
  return t('admin.systemKnowledge.visibilityScopes.internal')
}

/**
 * 拉取系统知识库列表（服务端分页+搜索）。
 * 将当前页码、页大小、搜索关键词透传给后端，并使用返回的 total_record 驱动分页器。
 */
const loadList = async () => {
  loading.value = true
  try {
    const result = await listSystemKnowledge({
      page: currentPage.value,
      page_size: pageSize.value,
      search_word: searchWord.value.trim(),
    })
    records.value = result.items || []
    // 优先使用服务端返回的 total_record，回退到 total 兼容旧响应
    totalRecord.value = result.total_record ?? result.total ?? 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.systemKnowledge.loadFailed')))
  } finally {
    loading.value = false
  }
}

/**
 * 触发搜索并重置到第一页，重新拉取服务端数据。
 */
const handleSearch = () => {
  currentPage.value = 1
  void loadList()
}

/**
 * 切换分页：更新当前页码并重新拉取服务端数据。
 */
const handlePageChange = (page: number) => {
  currentPage.value = page
  void loadList()
}

/**
 * 切换每页条数：重置到第一页并重新拉取服务端数据。
 */
const handlePageSizeChange = (size: number) => {
  pageSize.value = size
  currentPage.value = 1
  void loadList()
}

/**
 * 打开创建弹窗。
 */
const openCreateModal = () => {
  modalMode.value = 'create'
  editingId.value = ''
  formModel.value = { name: '', description: '', visibility_scope: 'internal' }
  modalVisible.value = true
}

/**
 * 打开编辑弹窗，回填表单。
 */
const openEditModal = (record: SystemKnowledgeRecord) => {
  modalMode.value = 'edit'
  editingId.value = record.id
  formModel.value = {
    name: record.name,
    description: record.description || '',
    visibility_scope: record.visibility_scope || 'internal',
  }
  modalVisible.value = true
}

/**
 * 提交创建/编辑表单，成功后保持当前页并刷新列表。
 */
const handleSubmit = async () => {
  const name = formModel.value.name.trim()
  if (!name) {
    Message.error(t('admin.systemKnowledge.modal.nameRequired'))
    return
  }
  submitting.value = true
  try {
    if (modalMode.value === 'create') {
      const payload: CreateSystemKnowledgeRequest = {
        name,
        description: formModel.value.description.trim(),
        visibility_scope: formModel.value.visibility_scope,
      }
      await createSystemKnowledge(payload)
      Message.success(t('admin.systemKnowledge.createSuccess'))
    } else {
      const payload: UpdateSystemKnowledgeRequest = {
        name,
        description: formModel.value.description.trim(),
        visibility_scope: formModel.value.visibility_scope,
      }
      await updateSystemKnowledge(editingId.value, payload)
      Message.success(t('admin.systemKnowledge.updateSuccess'))
    }
    modalVisible.value = false
    // 保持当前页（currentPage 不重置），刷新列表
    await loadList()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.systemKnowledge.loadFailed')))
  } finally {
    submitting.value = false
  }
}

/**
 * 删除系统知识库（由 a-popconfirm 确认后触发）。
 */
const handleDelete = async (record: SystemKnowledgeRecord) => {
  try {
    await deleteSystemKnowledge(record.id)
    Message.success(t('admin.systemKnowledge.deleteSuccess'))
    // 删除后若当前页只剩这一条且不在第一页，回退一页避免空页
    if (records.value.length <= 1 && currentPage.value > 1) {
      currentPage.value -= 1
    }
    await loadList()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.systemKnowledge.deleteFailed')))
  }
}

/**
 * 切换系统知识库 enabled 状态（即"对 Agent 是否可读"开关）。
 * enabled=true → Agent 可读，App 可引用
 * enabled=false → Agent 不可读，已引用的 App 检索无结果
 */
const handleToggleEnabled = async (record: SystemKnowledgeRecord, enabled: boolean) => {
  try {
    await updateSystemKnowledge(record.id, { enabled })
    record.enabled = enabled
    Message.success(
      enabled
        ? t('admin.systemKnowledge.enableSuccess')
        : t('admin.systemKnowledge.disableSuccess'),
    )
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.systemKnowledge.loadFailed')))
  }
}

// ==================== Prompt 模板页签 ====================
const promptLoading = ref(false)
const promptSaving = ref(false)
const promptResetting = ref(false)
const promptTemplates = ref<PromptTemplateItem[]>([])
const promptCategoryFilter = ref('')
const editingPromptKey = ref<string | null>(null)
const editingPromptItem = ref<PromptTemplateItem | null>(null)
const promptEditForm = ref({
  content: '',
  description: '',
})
const originalPromptContent = ref('')

const promptCategoryOptions = computed(() => [
  { value: '', label: t('admin.systemKnowledge.prompt.categories.all') },
  { value: 'routing', label: t('admin.systemKnowledge.prompt.categories.routing') },
  { value: 'general', label: t('admin.systemKnowledge.prompt.categories.general') },
])

const filteredPromptTemplates = computed(() => {
  if (!promptCategoryFilter.value) return promptTemplates.value
  return promptTemplates.value.filter(tp => tp.category === promptCategoryFilter.value)
})

const promptContentChanged = computed(() => promptEditForm.value.content !== originalPromptContent.value)

const loadPromptTemplates = async () => {
  promptLoading.value = true
  try {
    const res = await listPromptTemplates()
    promptTemplates.value = res.items
  } catch (e) {
    Message.error(getErrorMessage(e, t('common.loadFailed')))
  } finally {
    promptLoading.value = false
  }
}

const startEditPrompt = (item: PromptTemplateItem) => {
  editingPromptItem.value = item
  editingPromptKey.value = item.prompt_key
  promptEditForm.value = {
    content: item.content,
    description: item.description,
  }
  originalPromptContent.value = item.content
}

const closePromptEdit = () => {
  editingPromptItem.value = null
  editingPromptKey.value = null
  originalPromptContent.value = ''
}

const savePrompt = async () => {
  if (!editingPromptKey.value) return
  promptSaving.value = true
  try {
    const payload: { content?: string; description?: string } = {}
    if (promptContentChanged.value) payload.content = promptEditForm.value.content
    if (promptEditForm.value.description !== editingPromptItem.value?.description) {
      payload.description = promptEditForm.value.description
    }
    await updatePromptTemplate(editingPromptKey.value, payload)
    Message.success(t('admin.systemKnowledge.prompt.saveSuccess'))
    closePromptEdit()
    await loadPromptTemplates()
  } catch (e) {
    Message.error(getErrorMessage(e, t('common.saveFailed')))
  } finally {
    promptSaving.value = false
  }
}

const resetPrompt = async (item: PromptTemplateItem) => {
  promptResetting.value = true
  try {
    await resetPromptTemplate(item.prompt_key)
    Message.success(t('admin.systemKnowledge.prompt.resetSuccess'))
    await loadPromptTemplates()
  } catch (e) {
    Message.error(getErrorMessage(e, t('admin.systemKnowledge.prompt.resetFailed')))
  } finally {
    promptResetting.value = false
  }
}

/**
 * 切换到 prompts 页签时懒加载 prompt 模板列表（避免初始进入页面就请求）。
 */
watch(activeTab, (tab) => {
  if (tab === 'prompts' && promptTemplates.value.length === 0 && !promptLoading.value) {
    void loadPromptTemplates()
  }
})

onMounted(() => {
  void loadList()
})
</script>

<template>
  <section class="space-y-5">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold text-slate-900">{{ t('admin.systemKnowledge.title') }}</h1>
        <p class="mt-1 text-sm text-slate-500">{{ t('admin.systemKnowledge.description') }}</p>
      </div>
    </header>

    <a-tabs v-model:active-key="activeTab" type="rounded">
      <!-- ==================== 知识库页签 ==================== -->
      <a-tab-pane key="knowledge" :title="t('admin.systemKnowledge.title')">
        <section class="space-y-5 pt-4">
          <section class="flex flex-wrap items-center justify-between gap-3">
            <a-button v-if="canWrite" type="primary" @click="openCreateModal">
              {{ t('admin.systemKnowledge.createBtn') }}
            </a-button>
            <div class="flex items-center gap-2">
              <a-input
                v-model="searchWord"
                class="w-full sm:w-[260px]"
                :placeholder="t('admin.systemKnowledge.searchPlaceholder')"
                allow-clear
                @press-enter="handleSearch"
                @clear="handleSearch"
              />
              <a-button type="primary" :loading="loading" @click="handleSearch">
                {{ t('common.actions.search') }}
              </a-button>
              <a-button :loading="loading" @click="loadList">
                {{ t('common.actions.refresh') }}
              </a-button>
            </div>
          </section>

          <card-grid-skeleton v-if="loading && records.length === 0" :count="8" />

          <a-row v-else-if="records.length" :gutter="[16, 16]">
            <a-col
              v-for="record in records"
              :key="record.id"
              :xs="24"
              :sm="12"
              :md="8"
              :lg="6"
              :xl="6"
            >
              <a-card
                hoverable
                class="rounded-lg h-full overflow-hidden"
                :body-style="{ padding: '12px' }"
              >
                <div class="flex items-start gap-2.5 mb-2">
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-1.5 min-w-0">
                      <div class="text-sm font-bold text-gray-900 truncate">{{ record.name }}</div>
                      <a-tag size="small" :color="record.enabled ? 'green' : 'gray'">
                        {{
                          record.enabled
                            ? t('admin.systemKnowledge.enabled')
                            : t('admin.systemKnowledge.disabled')
                        }}
                      </a-tag>
                    </div>
                    <div class="text-[11px] text-gray-500 line-clamp-1">
                      {{ getVisibilityLabel(record.visibility_scope) }}
                    </div>
                  </div>
                  <!-- enabled 开关：控制系统知识库对 Agent 是否可读 -->
                  <a-tooltip
                    v-if="canWrite"
                    :content="
                      record.enabled
                        ? t('admin.systemKnowledge.toggleEnabledOn')
                        : t('admin.systemKnowledge.toggleEnabledOff')
                    "
                    position="tr"
                  >
                    <a-switch
                      :model-value="record.enabled"
                      size="small"
                      @change="(val: boolean | string | number) => handleToggleEnabled(record, Boolean(val))"
                    />
                  </a-tooltip>
                </div>

                <resource-card-description :text="record.description" />

                <div class="flex flex-wrap items-center gap-1.5 mt-2.5">
                  <a-tag size="small" :color="getVisibilityTagColor(record.visibility_scope)">
                    {{ getVisibilityLabel(record.visibility_scope) }}
                  </a-tag>
                </div>

                <div class="flex items-center gap-1.5 mt-2.5">
                  <div class="text-[11px] text-gray-400 truncate">
                    {{ record.creator_name || t('admin.systemKnowledge.creator') }} ·
                    {{ formatTimestampShort(record.updated_at) }}
                  </div>
                </div>

                <div
                  v-if="canWrite"
                  class="flex items-center justify-end gap-1.5 mt-2.5 pt-2 border-t border-gray-100 flex-wrap"
                >
                  <a-button size="mini" type="outline" @click="openEditModal(record)">
                    {{ t('admin.systemKnowledge.editBtn') }}
                  </a-button>
                  <a-popconfirm
                    :content="t('admin.systemKnowledge.deleteConfirm')"
                    :ok-text="t('admin.systemKnowledge.deleteBtn')"
                    type="warning"
                    @ok="handleDelete(record)"
                  >
                    <a-button size="mini" status="danger">
                      {{ t('admin.systemKnowledge.deleteBtn') }}
                    </a-button>
                  </a-popconfirm>
                </div>
              </a-card>
            </a-col>
          </a-row>

          <section
            v-else
            class="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center"
          >
            <h2 class="text-lg font-medium text-slate-900">{{ t('admin.systemKnowledge.empty') }}</h2>
            <p class="mt-2 text-sm text-slate-500">{{ emptyDescription }}</p>
          </section>

          <footer class="flex flex-wrap items-center justify-between gap-3">
            <span class="text-xs text-slate-400">
              {{ t('admin.systemKnowledge.total', { count: totalRecord }) }}
            </span>
            <a-pagination
              v-if="totalRecord > 0"
              :current="currentPage"
              :page-size="pageSize"
              :total="totalRecord"
              size="small"
              show-total
              show-page-size
              :page-size-options="[10, 20, 50, 100]"
              @change="handlePageChange"
              @page-size-change="handlePageSizeChange"
            />
          </footer>
        </section>
      </a-tab-pane>

      <!-- ==================== Prompt 模板页签 ==================== -->
      <a-tab-pane key="prompts" :title="t('admin.systemKnowledge.promptTab')">
        <section class="space-y-4 pt-4">
          <p class="text-sm text-slate-500">{{ t('admin.systemKnowledge.prompt.description') }}</p>

          <section class="flex flex-wrap items-center justify-between gap-3">
            <a-select
              v-model="promptCategoryFilter"
              class="w-48"
              :placeholder="t('admin.systemKnowledge.prompt.categories.all')"
              :options="promptCategoryOptions"
            />
            <a-button :loading="promptLoading" @click="loadPromptTemplates">
              {{ t('common.actions.refresh') }}
            </a-button>
          </section>

          <card-grid-skeleton v-if="promptLoading && promptTemplates.length === 0" :count="4" />

          <div v-else-if="filteredPromptTemplates.length" class="space-y-3">
            <div
              v-for="tp in filteredPromptTemplates"
              :key="tp.prompt_key"
              class="rounded-xl border border-slate-200 bg-white p-4 hover:shadow-sm transition-shadow"
            >
              <div class="flex items-start justify-between gap-3">
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2 mb-1 flex-wrap">
                    <span class="font-medium text-base text-gray-900">{{ tp.name }}</span>
                    <a-tag size="small" color="arcoblue">
                      {{ t(`admin.systemKnowledge.prompt.categories.${tp.category}`) }}
                    </a-tag>
                    <a-tag
                      v-if="tp.source === 'custom'"
                      size="small"
                      color="orange"
                    >
                      {{ t('admin.systemKnowledge.prompt.customized') }}
                    </a-tag>
                    <a-tag v-else size="small" color="gray">
                      {{ t('admin.systemKnowledge.prompt.catalog') }}
                    </a-tag>
                    <span class="text-xs px-2 py-0.5 bg-gray-50 text-gray-500 rounded">
                      v{{ tp.version }}
                    </span>
                  </div>
                  <div v-if="tp.description" class="text-sm text-gray-600 mb-1">
                    {{ tp.description }}
                  </div>
                  <div class="flex items-center gap-4 text-sm text-gray-400 mt-1">
                    <span class="font-mono text-xs">{{ tp.prompt_key }}</span>
                    <span class="text-xs">
                      {{ t('admin.systemKnowledge.prompt.updatedAt') }}:
                      {{ formatTimestampShort(tp.updated_at) }}
                    </span>
                  </div>
                  <div
                    v-if="tp.variables && Object.keys(tp.variables).length > 0"
                    class="mt-2 flex items-center gap-1.5 flex-wrap"
                  >
                    <span class="text-xs text-gray-500">
                      {{ t('admin.systemKnowledge.prompt.variables') }}:
                    </span>
                    <span
                      v-for="(_, key) in tp.variables"
                      :key="String(key)"
                      class="text-xs font-mono px-1.5 py-0.5 bg-gray-100 rounded"
                    >
                      {{ key }}
                    </span>
                  </div>
                  <div class="mt-2 text-xs font-mono bg-gray-50 rounded p-2 text-gray-500 line-clamp-2">
                    {{ tp.content.slice(0, 200) }}{{ tp.content.length > 200 ? '...' : '' }}
                  </div>
                </div>
                <div class="flex flex-col gap-2 shrink-0" v-if="canWrite">
                  <a-button size="mini" type="outline" @click="startEditPrompt(tp)">
                    {{ t('admin.systemKnowledge.editBtn') }}
                  </a-button>
                  <a-popconfirm
                    v-if="tp.source === 'custom'"
                    :content="t('admin.systemKnowledge.prompt.forkHint')"
                    :ok-text="t('admin.systemKnowledge.prompt.reset')"
                    type="warning"
                    :disabled="promptResetting"
                    @ok="resetPrompt(tp)"
                  >
                    <a-button size="mini" status="danger" :loading="promptResetting">
                      {{ t('admin.systemKnowledge.prompt.reset') }}
                    </a-button>
                  </a-popconfirm>
                </div>
              </div>
            </div>
          </div>

          <section
            v-else
            class="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center"
          >
            <h2 class="text-lg font-medium text-slate-900">
              {{ t('admin.systemKnowledge.prompt.empty') }}
            </h2>
          </section>
        </section>
      </a-tab-pane>
    </a-tabs>

    <!-- ==================== 知识库创建/编辑弹窗 ==================== -->
    <a-modal
      v-model:visible="modalVisible"
      :title="
        modalMode === 'create'
          ? t('admin.systemKnowledge.modal.createTitle')
          : t('admin.systemKnowledge.modal.updateTitle')
      "
      :confirm-loading="submitting"
      @ok="handleSubmit"
    >
      <a-form :model="formModel" layout="vertical">
        <a-form-item :label="t('admin.systemKnowledge.modal.nameLabel')" required>
          <a-input
            v-model="formModel.name"
            :placeholder="t('admin.systemKnowledge.modal.namePlaceholder')"
          />
        </a-form-item>
        <a-form-item :label="t('admin.systemKnowledge.modal.descriptionLabel')">
          <a-textarea
            v-model="formModel.description"
            :placeholder="t('admin.systemKnowledge.modal.descriptionPlaceholder')"
            :auto-size="{ minRows: 3, maxRows: 6 }"
          />
        </a-form-item>
        <a-form-item :label="t('admin.systemKnowledge.modal.visibilityLabel')">
          <a-select v-model="formModel.visibility_scope" :options="visibilityOptions" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- ==================== Prompt 编辑弹窗 ==================== -->
    <a-modal
      :visible="editingPromptKey !== null"
      :title="t('admin.systemKnowledge.prompt.editTitle')"
      :width="780"
      :mask-closable="false"
      :confirm-loading="promptSaving"
      :ok-loading="promptSaving"
      :ok-button-props="{
        disabled: !promptContentChanged && promptEditForm.description === editingPromptItem?.description,
      }"
      @ok="savePrompt"
      @cancel="closePromptEdit"
    >
      <div class="space-y-4">
        <div
          v-if="editingPromptItem?.source === 'custom'"
          class="flex items-center gap-2"
        >
          <a-tag size="small" color="orange">
            {{ t('admin.systemKnowledge.prompt.customized') }}
          </a-tag>
        </div>
        <a-form layout="vertical">
          <a-form-item :label="t('admin.systemKnowledge.prompt.descriptionLabel')">
            <a-input
              v-model="promptEditForm.description"
              :placeholder="t('admin.systemKnowledge.prompt.descriptionPlaceholder')"
            />
          </a-form-item>
          <a-form-item>
            <template #label>
              <div class="flex items-center gap-2">
                <span>{{ t('admin.systemKnowledge.prompt.contentLabel') }}</span>
                <a-tag v-if="promptContentChanged" size="small" color="orange">
                  {{ t('admin.systemKnowledge.prompt.contentModified') }}
                </a-tag>
              </div>
            </template>
            <a-textarea
              v-model="promptEditForm.content"
              :auto-size="{ minRows: 18, maxRows: 30 }"
              class="font-mono text-sm"
            />
            <template #extra>
              {{ t('admin.systemKnowledge.prompt.contentHint') }}
            </template>
          </a-form-item>
        </a-form>
        <p class="text-xs text-slate-400">
          {{ t('admin.systemKnowledge.prompt.forkHint') }}
        </p>
      </div>
    </a-modal>
  </section>
</template>

<style scoped>
.line-clamp-1 {
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
