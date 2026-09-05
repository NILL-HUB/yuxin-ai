<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import moment from 'moment'
import type { ValidatedError } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  useCreateOrUpdateKnowledgeBase,
  useGenerateKnowledgeBaseIconPreview,
  useGetKnowledgeBase,
  useGetKnowledgeBasesWithPage,
  useRegenerateKnowledgeBaseIcon,
} from '@/hooks/use-knowledge-base'
import { deleteKnowledgeBase } from '@/services/knowledge-base'
import RecycleBinDeleteModal from '@/components/recycle-bin/UserRecycleBinDeleteModal.vue'
import ExternalDataSourceModal from './components/ExternalDataSourceModal.vue'
import { useUploadImage } from '@/hooks/use-upload-file'
import { useAccountStore } from '@/stores/account'
import IconUploadGenerator from '@/components/IconUploadGenerator.vue'
import { Message } from '@arco-design/web-vue'
import { getUserAvatarUrl } from '@/utils/helper'
import { getErrorMessage } from '@/utils/error'
import type { GetKnowledgeBasesWithPageResponse } from '@/models/knowledge-base'

// 数据集列表项：后端列表接口会返回相关应用计数，模型未声明该字段，这里局部扩展
type DatasetListItem = GetKnowledgeBasesWithPageResponse['data']['list'][number] & {
  related_app_count?: number
}

// 1.定义页面所需数据
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const accountStore = useAccountStore()
let updateDatasetID = ''
const { knowledgeBase: dataset, loadKnowledgeBase: loadDataset } = useGetKnowledgeBase()
const {
  loading,
  knowledgeBases: datasets,
  paginator,
  loadKnowledgeBases: loadDatasets,
} = useGetKnowledgeBasesWithPage()
// 带 related_app_count 字段的本地类型化列表
const datasetList = computed<DatasetListItem[]>(() => datasets.value as DatasetListItem[])
const { image_url, handleUploadImage } = useUploadImage()
const {
  loading: submitLoading,
  form,
  formRef,
  saveKnowledgeBase: saveDataset,
  showUpdateModal,
  updateShowUpdateModal,
} = useCreateOrUpdateKnowledgeBase()
// 删除确认卡片：进入回收站 + 选择留存天数
const deleteTarget = ref<{ id: string; name: string } | null>(null)
const deleteLoading = ref(false)
const handleDelete = (dataset: DatasetListItem) => {
  deleteTarget.value = { id: String(dataset.id), name: String(dataset.name || '') }
}
const confirmDelete = async (retentionDays: number) => {
  if (!deleteTarget.value) return
  deleteLoading.value = true
  try {
    await deleteKnowledgeBase(deleteTarget.value.id, retentionDays)
    Message.success(t('space.datasets.deleteSuccess'))
    deleteTarget.value = null
    await loadDatasets(true)
  } catch (error) {
    Message.error(getErrorMessage(error, t('space.datasets.deleteFailed')))
  } finally {
    deleteLoading.value = false
  }
}
const { loading: regenerateIconLoading, handleRegenerateIcon } = useRegenerateKnowledgeBaseIcon()
const {
  loading: generateIconPreviewLoading,
  handleGenerateIconPreview,
} = useGenerateKnowledgeBaseIconPreview()
const search_word = computed(() => {
  return String(route.query?.search_word ?? '')
})
// 搜索框输入态（本地受控输入，route 变化时重置回查询值）
const searchInput = ref(search_word.value)
// 搜索防抖计时器
let searchDebounceTimer: ReturnType<typeof setTimeout> | undefined
// 外部数据源弹窗开关
const externalSourceVisible = ref(false)
// 模态窗模式：新建/更新
const isUpdateMode = computed(() => updateDatasetID !== '')
// 图标生成 loading：合并两种模式的 loading
const iconGenerateLoading = computed(() => regenerateIconLoading.value || generateIconPreviewLoading.value)

// 2.1 统计卡聚合（真实数据，不造假）：总数 / 文档数 / 应用引用数
const totalDatasetCount = computed(() => {
  return paginator.value.total_record ?? datasetList.value.length
})
const totalDocumentCount = computed(() => {
  return datasetList.value.reduce((sum, dataset) => sum + (dataset.document_count || 0), 0)
})
const totalAppReferenceCount = computed(() => {
  return datasetList.value.reduce((sum, dataset) => sum + (dataset.related_app_count || 0), 0)
})

// 2.2 搜索框：回车或防抖 300ms 后写回路由 query.search_word（触发既有 watch 刷新）
const handleSearchInput = (value: string) => {
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  searchDebounceTimer = setTimeout(() => {
    const word = value.trim()
    if (word === search_word.value) return
    router.push({ query: { ...route.query, search_word: word || undefined } })
  }, 300)
}
const handleSearchEnter = () => {
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  const word = searchInput.value.trim()
  if (word === search_word.value) return
  router.push({ query: { ...route.query, search_word: word || undefined } })
}

// 2.定义上传图标处理器
const handleUploadIcon = async (file: File) => {
  await handleUploadImage(file)
  form.value.icon = image_url.value
  form.value.fileList = [{ uid: '1', name: t('space.datasets.modal.iconPlaceholder'), url: image_url.value }]
  // 显式触发 fileList 字段校验，清除"图标不能为空"错误
  formRef.value?.validateField('fileList')
  Message.success(t('space.datasets.uploadSuccess'))
}

// 3.定义生成图标处理器
const handleGenerateIcon = async () => {
  if (!form.value.name || form.value.name.trim() === '') {
    Message.warning(t('space.datasets.enterNameFirst'))
    return
  }

  try {
    // 根据模式调用不同的生成接口
    // 新建模式：仅需 name + description，无需 KB id
    // 更新模式：调用 regenerateIcon，需要已存在的 KB id
    const iconUrl = isUpdateMode.value
      ? await handleRegenerateIcon(updateDatasetID)
      : await handleGenerateIconPreview(form.value.name, form.value.description || '')
    if (iconUrl) {
      form.value.icon = iconUrl
      form.value.fileList = [{ uid: '1', name: t('space.datasets.modal.iconPlaceholder'), url: iconUrl }]
      // 显式触发 fileList 字段校验，清除"图标不能为空"错误
      formRef.value?.validateField('fileList')
      Message.success(t('space.datasets.generateSuccess'))
    }
  } catch {
    // 错误已在 hooks 中处理
  }
}

// 4.定义滚动数据分页处理器
const handleScroll = async (event: UIEvent) => {
  // 2.1 获取滚动距离、可滚动的最大距离、客户端/浏览器窗口的高度
  const { scrollTop, scrollHeight, clientHeight } = event.target as HTMLElement

  // 2.2 判断是否滑动到底部
  if (scrollTop + clientHeight >= scrollHeight - 10) {
    if (loading.value) return
    await loadDatasets(false, search_word.value)
  }
}

// 5.定义编辑知识库处理器
const handleUpdate = (dataset_id: string) => {
  updateShowUpdateModal(true, async () => {
    // 1.调用api获取知识库详情
    await loadDataset(dataset_id)
    updateDatasetID = dataset_id

    // 2.更新表单数据
    formRef.value?.resetFields()
    form.value.fileList = [{ uid: '1', name: t('space.datasets.modal.iconPlaceholder'), url: dataset.value.icon }]
    form.value.icon = dataset.value.icon
    form.value.name = dataset.value.name
    form.value.description = dataset.value.description
  })
}

// 5.1 定义新建知识库处理器
const handleCreate = () => {
  updateShowUpdateModal(true, () => {
    updateDatasetID = ''
    formRef.value?.resetFields()
    form.value.icon = ''
    form.value.fileList = []
    form.value.name = ''
    form.value.description = ''
  })
}

// 6.定义取消显示模态窗
const handleCancel = async () => {
  updateShowUpdateModal(false, async () => {
    // 1.重置整个表单数据
    updateDatasetID = ''
    formRef.value?.resetFields()
  })
}

// 7.定义提交模态窗处理器
const handleSubmit = async ({ errors }: { errors: Record<string, ValidatedError> | undefined }) => {
  // 1.如果出错则直接抛出
  if (errors) return

  // 2.调用保存知识库服务
  await saveDataset(updateDatasetID)

  // 3.关闭模态窗并且刷新数据
  handleCancel()
  await loadDatasets(true)
}

// 7.1 自绘保存按钮：先手动校验表单再提交
const submitForm = async () => {
  if (submitLoading.value) return
  try {
    const errors = await formRef.value?.validate()
    await handleSubmit({ errors: errors || undefined })
  } catch {
    // validate 失败会 reject，静默处理（错误提示已由表单展示）
  }
}

// 8.监听路由query的变化
watch(
  () => route.query?.search_word,
  (newValue) => {
    if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
    searchInput.value = String(newValue ?? '')
    loadDatasets(true, String(newValue))
  },
)

// 9.页面DOM加载后加载数据
onMounted(() => {
  // 防御性清理：热重载/会话弹窗动画中断可能遗留 display:none 的空壳 modal wrapper，
  // 它们不可见但会拦截页面点击，导致「弹窗关不掉只能刷新」。此处仅移除空壳容器，
  // 不影响任何可见 UI 与正常弹窗生命周期。
  requestAnimationFrame(() => {
    document.querySelectorAll('.arco-modal-wrapper').forEach((wrapper) => {
      const modal = wrapper.querySelector('.arco-modal')
      if (!modal || getComputedStyle(modal).display === 'none') {
        wrapper.remove()
      }
    })
  })
  loadDatasets(true, search_word.value)
})

// 10.定义卡片点击处理器
const handleCardClick = (datasetId: string) => {
  router.push({
    name: 'space-datasets-documents-list',
    params: { dataset_id: datasetId },
  })
}
</script>

<template>
  <div class="kb-page flex h-full w-full flex-col overflow-hidden">
    <!-- ===== 顶部工具栏区（固定不滚动，粉色知识库原型对齐） ===== -->
    <header class="kb-header shrink-0">
      <div class="mx-auto w-full max-w-6xl px-4 py-5 sm:px-6 lg:px-8">
        <div class="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <!-- 左侧：标题 + 副标题 -->
          <div class="min-w-0">
            <div class="flex items-center gap-2.5">
              <span class="kb-header-mark flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-white">
                <icon-book class="text-lg" />
              </span>
              <h1 class="kb-title truncate text-xl font-bold sm:text-2xl">{{ t('space.datasets.title') }}</h1>
            </div>
            <p class="kb-subtitle mt-1.5 max-w-xl text-xs leading-relaxed sm:text-sm">
              {{ t('space.datasets.subtitle') }}
            </p>
          </div>
          <!-- 右侧：搜索 + 外部数据源 -->
          <div class="flex w-full shrink-0 flex-col gap-2.5 sm:flex-row sm:items-center lg:w-auto">
            <div class="kb-search-box w-full sm:w-64">
              <icon-search class="kb-search-ico" />
              <input
                v-model="searchInput"
                type="search"
                class="kb-search-input-el"
                :placeholder="t('space.datasets.searchPlaceholder')"
                @input="handleSearchInput(($event.target as HTMLInputElement).value)"
                @keyup.enter="handleSearchEnter"
              />
              <button
                v-if="searchInput"
                type="button"
                class="kb-search-clear"
                aria-label="清除搜索"
                @click="
                  searchInput = '';
                  handleSearchEnter();
                "
              >
                <icon-close />
              </button>
            </div>
            <button type="button" class="kb-btn kb-btn-outline" @click="externalSourceVisible = true">
              <icon-cloud class="kb-btn-ico" />
              {{ t('externalDataSource.title') }}
            </button>
          </div>
        </div>
      </div>
    </header>

    <!-- ===== 可滚动主体区（保留加载更多/触底分页交互） ===== -->
    <div class="kb-body relative min-h-0 flex-1 overflow-hidden">
      <a-spin
        :loading="loading"
        class="kb-scroll-spin scrollbar-w-none block h-full w-full overflow-x-hidden"
        @scroll="handleScroll"
      >
        <!-- 内容列 -->
        <div class="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-8">
          <!-- ① 统计卡：真实聚合 -->
          <section aria-label="统计概览" class="kb-stats-grid">
            <article class="stat-card">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <span class="stat-icon">
                    <icon-storage />
                  </span>
                  <span class="stat-label">{{ t('space.datasets.statDataset') }}</span>
                </div>
              </div>
              <p class="stat-value">
                {{ totalDatasetCount }}
              </p>
            </article>
            <article class="stat-card">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <span class="stat-icon stat-icon-doc">
                    <icon-file />
                  </span>
                  <span class="stat-label">{{ t('space.datasets.statDocuments') }}</span>
                </div>
              </div>
              <p class="stat-value">
                {{ totalDocumentCount }}
              </p>
            </article>
            <article class="stat-card">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <span class="stat-icon stat-icon-app">
                    <icon-link />
                  </span>
                  <span class="stat-label">{{ t('space.datasets.statApps') }}</span>
                </div>
              </div>
              <p class="stat-value">
                {{ totalAppReferenceCount }}
              </p>
            </article>
          </section>

          <!-- ② 数据集分区标题行：左计数 + 右新建 -->
          <div class="kb-section-row">
            <span class="count-chip">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                class="count-chip-ico"
                aria-hidden="true"
              >
                <polygon points="12 2 2 7 12 12 22 7 12 2" />
                <polyline points="2 17 12 22 22 17" />
                <polyline points="2 12 12 17 22 12" />
              </svg>
              {{ t('space.datasets.totalCount', { count: totalDatasetCount }) }}
            </span>
            <button type="button" class="kb-btn kb-btn-primary" @click="handleCreate">
              <icon-plus class="kb-btn-ico" />
              {{ t('space.datasets.create') }}
            </button>
          </div>

          <!-- ③ 数据集卡片网格 -->
          <div class="kb-card-grid">
            <!-- 有数据的UI状态 -->
            <a-card
              v-for="dataset in datasetList"
              :key="dataset.id"
              hoverable
              class="dataset-card"
              @click="handleCardClick(dataset.id)"
            >
              <!-- 顶部：图标 + 名称 + 操作菜单 -->
              <div class="flex items-center gap-3">
                <a-avatar :size="44" shape="square" class="dataset-avatar" :image-url="dataset.icon">
                  {{ String(dataset.name || '?').trim().charAt(0) }}
                </a-avatar>
                <div class="min-w-0 flex-1">
                  <div class="dataset-name line-clamp-1">{{ dataset.name }}</div>
                  <div class="dataset-meta mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                    <span>{{ dataset.document_count || 0 }} 文档</span>
                    <span class="meta-dot"></span>
                    <span>{{ Math.round(dataset.character_count / 1000) }}k 字</span>
                    <span class="meta-dot"></span>
                    <span>{{ dataset.related_app_count || 0 }} 应用</span>
                  </div>
                </div>
                <a-dropdown position="br" @click.stop>
                  <button type="button" class="dataset-more-btn" aria-label="数据集操作">
                    <icon-more />
                  </button>
                  <template #content>
                    <a-doption @click="() => handleUpdate(dataset.id)">
                      <template #icon>
                        <icon-settings />
                      </template>
                      {{ t('space.datasets.settings') }}
                    </a-doption>
                    <a-doption class="!text-red-500" @click="() => handleDelete(dataset)">
                      <template #icon>
                        <icon-delete />
                      </template>
                      {{ t('space.datasets.delete') }}
                    </a-doption>
                  </template>
                </a-dropdown>
              </div>
              <!-- 描述 -->
              <p class="dataset-desc line-clamp-3 break-all">{{ dataset.description || '-' }}</p>
              <!-- 底部归属信息 -->
              <div class="dataset-footer mt-auto flex items-center gap-1.5">
                <a-avatar
                  :size="22"
                  class="dataset-owner-avatar shrink-0"
                  :image-url="getUserAvatarUrl(accountStore.account.avatar, accountStore.account.name)"
                >
                  {{ (accountStore.account.name || t('space.datasets.unknownUser'))[0] }}
                </a-avatar>
                <span class="truncate text-xs text-muted">
                  {{ accountStore.account.name || t('space.datasets.unknownUser') }} · {{ t('space.datasets.recentEdited') }}
                  {{ moment((dataset.updated_at || dataset.created_at) * 1000).format('MM-DD HH:mm') }}
                </span>
              </div>
            </a-card>

            <!-- 空数据/空搜索匹配提示 -->
            <div v-if="datasetList.length === 0" class="kb-empty">
              <a-empty
                :description="search_word ? t('space.datasets.emptySearch') : t('space.datasets.empty')"
                class="flex w-full flex-col items-center justify-center py-14"
              />
            </div>
          </div>

          <!-- ④ 加载更多 / 已加载完 -->
          <div v-if="paginator.total_page >= 2" class="pb-2">
            <div v-if="loading" class="py-3 text-center">
              <a-spin class="inline-flex items-center gap-2 text-muted">
                <template #icon>
                  <icon-loading />
                </template>
                {{ t('space.datasets.loading') }}
              </a-spin>
            </div>
            <div v-else-if="paginator.current_page > paginator.total_page" class="py-3 text-center text-sm text-muted">
              {{ t('space.datasets.loadedAll') }}
            </div>
          </div>
        </div>
      </a-spin>
    </div>

    <!-- ===== 外部数据源弹窗 ===== -->
    <ExternalDataSourceModal v-model:visible="externalSourceVisible" />

    <!-- 修改模态窗 -->
    <a-modal
      :width="520"
      :visible="showUpdateModal"
      hide-title
      :footer="false"
      modal-class="rounded-xl"
      @cancel="handleCancel"
    >
      <!-- 顶部标题 -->
      <div class="flex items-center justify-between">
        <div class="text-lg font-bold text-text-2">
          {{ isUpdateMode ? t('space.datasets.modal.updateTitle') : t('space.datasets.modal.createTitle') }}
        </div>
        <button type="button" class="kb-modal-close" aria-label="关闭" @click="handleCancel">
          <icon-close />
        </button>
      </div>
      <!-- 中间表单 -->
      <div class="pt-6">
        <a-form ref="formRef" :model="form" @submit="handleSubmit" layout="vertical">
          <a-form-item
            field="fileList"
            hide-label
          >
            <IconUploadGenerator
              :name="form.name"
              :description="form.description"
              :icon="form.icon"
              :file-list="form.fileList"
              :loading="iconGenerateLoading"
              :placeholder="t('space.datasets.modal.iconPlaceholder')"
              :on-upload="handleUploadIcon"
              :on-generate="handleGenerateIcon"
              @update:icon="(val) => (form.icon = val)"
              @update:fileList="(val) => (form.fileList = val)"
            />
          </a-form-item>
          <a-form-item
            field="name"
            :label="t('space.datasets.modal.nameLabel')"
            asterisk-position="end"
            :rules="[{ required: true, message: t('space.datasets.modal.nameRequired') }]"
          >
            <a-input
              v-model="form.name"
              :placeholder="t('space.datasets.modal.namePlaceholder')"
              show-word-limit
              :max-length="60"
            />
          </a-form-item>
          <a-form-item field="description" :label="t('space.datasets.modal.descriptionLabel')" asterisk-position="end">
            <a-textarea
              v-model="form.description"
              :auto-size="{ minRows: 4, maxRows: 6 }"
              :placeholder="t('space.datasets.modal.descriptionPlaceholder')"
            />
          </a-form-item>
          <!-- embedding 模型由后端自动选择（维度优先+健康度），用户不能自选，避免维度错位 -->
          <!-- 底部按钮 -->
          <div class="flex items-center justify-between">
            <div class=""></div>
            <a-space :size="16">
              <button type="button" class="kb-btn kb-btn-ghost" @click="handleCancel">
                {{ t('common.actions.cancel') }}
              </button>
              <button
                type="button"
                class="kb-btn kb-btn-primary"
                :class="{ 'is-loading': submitLoading }"
                :disabled="submitLoading"
                @click="submitForm"
              >
                {{ submitLoading ? t('space.datasets.saving') : t('common.actions.save') }}
              </button>
            </a-space>
          </div>
        </a-form>
      </div>
    </a-modal>

    <!-- 删除知识库确认（进入回收站 + 选择留存天数） -->
    <RecycleBinDeleteModal
      :visible="deleteTarget !== null"
      :title="t('space.datasets.delete')"
      :resource-name="deleteTarget?.name"
      :loading="deleteLoading"
      :hint="t('userRecycleBin.deleteHint')"
      @update:visible="(v) => !v && (deleteTarget = null)"
      @confirm="confirmDelete"
    >
      <p class="text-sm text-muted">
        {{ deleteTarget ? t('space.datasets.deleteContent', { name: deleteTarget.name }) : '' }}
      </p>
    </RecycleBinDeleteModal>
  </div>
</template>

<style scoped>
/* ============================================================
   知识库列表 · 粉色翻新（对齐 yuxin-barbie-redesign/pages/knowledge.html）
   语义色统一走 aicss 变量；粉色强调用 tw 主题变量（barbie 主题下为粉系）
   ============================================================ */
.kb-page {
  background: var(--aicss-bg);
}

/* ---- 顶部工具栏 ---- */
.kb-header {
  position: relative;
  z-index: 2;
  background: var(--tw-surface);
  border-bottom: 1px solid var(--tw-border);
  box-shadow: 0 1px 2px rgba(233, 30, 99, 0.04);
}
.kb-header-mark {
  background: linear-gradient(135deg, var(--tw-accent), var(--tw-brand));
  box-shadow: 0 4px 12px rgba(233, 30, 99, 0.22);
}
.kb-title {
  color: var(--aicss-text);
  letter-spacing: -0.01em;
}
.kb-subtitle {
  color: var(--aicss-muted);
}

/* ---- 自绘搜索框 ---- */
.kb-search-box {
  position: relative;
  display: flex;
  align-items: center;
  height: 42px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-surface);
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}
.kb-search-box:focus-within {
  border-color: var(--aicss-accent);
  box-shadow: 0 0 0 3px var(--aicss-accent-soft);
}
.kb-search-ico {
  position: absolute;
  left: 14px;
  font-size: 15px;
  color: var(--aicss-muted);
  pointer-events: none;
}
.kb-search-input-el {
  width: 100%;
  height: 100%;
  padding: 0 34px 0 38px;
  border: none;
  background: transparent;
  color: var(--aicss-text);
  font-size: 13px;
  font-family: inherit;
  outline: none;
}
.kb-search-input-el::placeholder {
  color: var(--aicss-muted);
}
.kb-search-input-el::-webkit-search-cancel-button {
  display: none;
}
.kb-search-clear {
  position: absolute;
  right: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--aicss-muted);
  cursor: pointer;
  transition:
    background 0.2s ease,
    color 0.2s ease;
}
.kb-search-clear:hover {
  background: var(--aicss-surface-2);
  color: var(--aicss-text);
}
.kb-search-clear svg,
.kb-search-clear :deep(svg) {
  width: 12px;
  height: 12px;
}

/* ---- 自绘按钮（kb-btn 族，供本页/弹窗共用） ---- */
.kb-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 42px;
  padding: 0 18px;
  border: 1px solid transparent;
  border-radius: var(--aicss-radius);
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  line-height: 1;
  cursor: pointer;
  white-space: nowrap;
  transition:
    opacity 0.2s ease,
    background 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease,
    transform 0.2s var(--aicss-ease, ease),
    box-shadow 0.2s ease;
}
.kb-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.kb-btn-ico {
  font-size: 15px;
}
.kb-btn svg,
.kb-btn :deep(svg) {
  width: 15px;
  height: 15px;
}
.kb-btn-primary {
  background: linear-gradient(135deg, var(--aicss-accent) 0%, #ff5c8d 100%);
  color: #fff;
  box-shadow: var(--aicss-shadow-card);
}
.kb-btn-primary:hover:not(:disabled) {
  opacity: 0.92;
  transform: translateY(-1px);
  box-shadow: var(--aicss-shadow-elevated);
}
.kb-btn-primary:active:not(:disabled) {
  transform: translateY(0);
}
.kb-btn-outline {
  border-color: var(--aicss-border);
  background: var(--aicss-surface);
  color: var(--aicss-text);
  box-shadow: var(--aicss-shadow-card);
}
.kb-btn-outline:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--aicss-accent) 45%, var(--aicss-border));
  color: var(--aicss-accent-text);
  background: var(--aicss-accent-soft);
}
.kb-btn-outline svg,
.kb-btn-outline :deep(svg) {
  color: var(--aicss-accent);
}
.kb-btn-ghost {
  height: 38px;
  padding: 0 16px;
  border-color: var(--aicss-border);
  background: var(--aicss-surface);
  color: var(--aicss-text);
  border-radius: var(--aicss-radius-sm);
}
.kb-btn-ghost:hover:not(:disabled) {
  border-color: var(--aicss-border-strong);
  background: var(--aicss-bg-subtle);
}
.kb-btn.is-loading {
  opacity: 0.7;
  cursor: progress;
}

/* ---- 统计卡：浅粉渐变卡片 ---- */
.kb-stats-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
.stat-card {
  position: relative;
  overflow: hidden;
  padding: 18px 20px;
  border-radius: var(--aicss-radius-lg);
  border: 1px solid var(--tw-border);
  background:
    radial-gradient(120% 140% at 100% 0%, rgba(255, 158, 197, 0.16) 0%, transparent 55%),
    linear-gradient(160deg, var(--tw-surface) 0%, var(--tw-brand-soft) 100%);
  box-shadow: var(--aicss-shadow-card);
  transition:
    transform 0.25s var(--aicss-ease),
    box-shadow 0.25s var(--aicss-ease),
    border-color 0.25s var(--aicss-ease);
}
.stat-card::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 4px;
  height: 100%;
  background: linear-gradient(180deg, var(--tw-accent), var(--tw-brand));
  opacity: 0.9;
}
.stat-card:hover {
  transform: translateY(-2px);
  border-color: var(--tw-border-strong);
  box-shadow: var(--aicss-shadow-elevated);
}
.stat-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--tw-accent), var(--tw-brand));
  color: #fff;
  box-shadow: 0 3px 8px rgba(233, 30, 99, 0.2);
}
.stat-icon-doc {
  background: linear-gradient(135deg, #ff80ab, #e91e63);
}
.stat-icon-app {
  background: linear-gradient(135deg, #f48fb1, #c2185b);
}
.stat-icon :deep(svg) {
  width: 16px;
  height: 16px;
}
.stat-label {
  color: var(--aicss-text-2);
  font-size: 14px;
  font-weight: 500;
}
.stat-value {
  margin-top: 12px;
  color: var(--aicss-text);
  font-size: 30px;
  font-weight: 700;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}

/* ---- 数据集分区标题行 ---- */
.kb-section-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 28px;
  margin-bottom: 16px;
}
.count-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid var(--tw-border);
  background: var(--aicss-surface-2);
  color: var(--aicss-muted);
  font-size: 12px;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.count-chip-ico {
  width: 14px;
  height: 14px;
  color: var(--tw-brand);
}

/* ---- 数据集卡片网格（纯 CSS grid 保证触底滚动可用） ---- */
.kb-card-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
}
.dataset-card {
  position: relative;
  display: flex;
  flex-direction: column;
  cursor: pointer;
  border: 1px solid var(--tw-border) !important;
  border-radius: var(--aicss-radius-lg) !important;
  background: var(--tw-card) !important;
  box-shadow: var(--aicss-shadow-card) !important;
  transition:
    transform 0.25s var(--aicss-ease),
    box-shadow 0.25s var(--aicss-ease),
    border-color 0.25s var(--aicss-ease);
}
.dataset-card:hover {
  transform: translateY(-3px);
  border-color: var(--tw-brand-soft) !important;
  box-shadow: var(--aicss-shadow-elevated) !important;
}
.dataset-card :deep(.arco-card-body) {
  display: flex;
  flex-direction: column;
  flex: 1;
  height: 100%;
  padding: 18px;
}
.dataset-avatar {
  flex-shrink: 0;
  border-radius: var(--aicss-radius);
  background: linear-gradient(135deg, var(--tw-accent), var(--tw-brand));
  color: #fff;
  font-weight: 600;
}
.dataset-name {
  color: var(--aicss-text);
  font-size: 15px;
  font-weight: 600;
}
.dataset-meta {
  color: var(--aicss-muted);
  font-variant-numeric: tabular-nums;
}
.meta-dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--tw-border-strong);
}
.dataset-more-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--aicss-subtle);
  border-radius: 8px;
  cursor: pointer;
  transition:
    background 0.2s ease,
    color 0.2s ease;
}
.dataset-more-btn svg,
.dataset-more-btn :deep(svg) {
  width: 15px;
  height: 15px;
}
.dataset-more-btn:hover {
  color: var(--aicss-accent-text);
  background: var(--aicss-accent-soft);
}
.dataset-desc {
  margin-top: 14px;
  color: var(--aicss-muted);
  font-size: 13px;
  line-height: 1.6;
  min-height: 62px;
}
.dataset-footer {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--tw-border);
  color: var(--aicss-muted);
}
.dataset-owner-avatar {
  background: linear-gradient(135deg, var(--tw-accent), var(--tw-brand));
  color: #fff;
  font-size: 12px;
}

/* 空态 */
.kb-empty {
  grid-column: 1 / -1;
  border: 1px dashed var(--tw-border-strong);
  border-radius: var(--aicss-radius-lg);
  background: var(--aicss-bg-subtle);
}

/* ---- 滚动容器（a-spin 内部） ---- */
.kb-scroll-spin {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  margin: 0 !important;
}
.kb-scroll-spin :deep(.arco-spin-children) {
  width: 100%;
}

/* ---- 新建/编辑数据集弹窗自绘对齐 ---- */
:deep(.arco-modal) {
  border-radius: var(--aicss-radius-lg);
  background: var(--aicss-surface);
}
.kb-modal-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--aicss-muted);
  cursor: pointer;
  transition:
    background 0.2s ease,
    color 0.2s ease;
}
.kb-modal-close:hover {
  background: var(--aicss-surface-2);
  color: var(--aicss-text);
}
.kb-modal-close svg,
.kb-modal-close :deep(svg) {
  width: 14px;
  height: 14px;
}

/* 表单输入控件圆角/边框统一主题（不改 Arco 主色，仅视觉对齐） */
.kb-page :deep(.arco-form .arco-input) {
  border-radius: var(--aicss-radius-sm) !important;
}
.kb-page :deep(.arco-form .arco-textarea) {
  border-radius: var(--aicss-radius-sm) !important;
}
.kb-page :deep(.arco-form .arco-input-wrapper),
.kb-page :deep(.arco-form .arco-textarea-wrapper) {
  border-radius: var(--aicss-radius-sm) !important;
  background: var(--aicss-bg-subtle) !important;
}
.kb-page :deep(.arco-form .arco-input-wrapper:focus-within),
.kb-page :deep(.arco-form .arco-textarea-wrapper:focus-within) {
  border-color: var(--aicss-accent) !important;
  box-shadow: 0 0 0 3px var(--aicss-accent-soft) !important;
}
.kb-page :deep(.arco-form-item-label) {
  color: var(--aicss-text-2) !important;
  font-weight: 500;
}
.kb-page :deep(.arco-modal) {
  background: var(--aicss-surface) !important;
  border-radius: var(--aicss-radius-lg) !important;
}
.kb-page :deep(.arco-modal-content) {
  color: var(--aicss-text);
}

/* ---- 移动端适配：393px 不溢出 ---- */
@media (max-width: 767px) {
  .kb-stats-grid {
    grid-template-columns: 1fr;
  }
  .stat-card {
    padding: 15px 16px;
  }
  .stat-value {
    font-size: 26px;
  }
  .kb-section-row {
    flex-wrap: wrap;
    align-items: center;
  }
  .kb-card-grid {
    grid-template-columns: 1fr;
    gap: 16px;
  }
}

:deep(.arco-row) {
  width: 100% !important;
  max-width: 100% !important;
}
</style>
