<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Message, type FileItem } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { del } from '@/utils/request'
import type { BaseResponse } from '@/models/base'
import CardGridSkeleton from '@/components/skeletons/CardGridSkeleton.vue'
import ResourceCardDescription from '@/components/ResourceCardDescription.vue'
import RecycleBinDeleteModal from '@/components/admin/RecycleBinDeleteModal.vue'
import { getErrorMessage } from '@/utils/error'
import { formatTimestampShort } from '@/utils/time-formatter'
import { useAdminStore } from '@/stores/admin'
import type {
  AdminHitTestItem,
  AdminKnowledgeDocument,
  CreateSystemKnowledgeRequest,
  SystemKnowledgeRecord,
  UpdateSystemKnowledgeRequest,
} from '@/models/admin-system-knowledge'
import {
  createAdminTextDocument,
  createSystemKnowledge,
  deleteAdminKnowledgeDocument,
  deleteSystemKnowledge,
  getAdminKnowledgeDocument,
  hitTestAdminKnowledge,
  listAdminDocumentSegments,
  listAdminKnowledgeDocuments,
  listSystemKnowledge,
  updateAdminTextDocument,
  updateSystemKnowledge,
  uploadAdminKnowledgeDocument,
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
  editingRecord.value = null
  formModel.value = { name: '', description: '', visibility_scope: 'internal' }
  modalVisible.value = true
}

/**
 * 打开编辑弹窗，回填表单。
 */
const editingRecord = ref<SystemKnowledgeRecord | null>(null)

const openEditModal = (record: SystemKnowledgeRecord) => {
  modalMode.value = 'edit'
  editingId.value = record.id
  editingRecord.value = record
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
 * 打开删除确认弹窗（选择留存时间后删除，进入回收站）。
 */
const deleteTarget = ref<SystemKnowledgeRecord | null>(null)
const deleteRetentionDays = ref(30)
const deleteConfirmLoading = ref(false)

const retentionOptions = computed(() => [
  { value: 7, label: t('admin.systemKnowledge.deleteModal.retentionOptions.d7') },
  { value: 30, label: t('admin.systemKnowledge.deleteModal.retentionOptions.d30') },
  { value: 90, label: t('admin.systemKnowledge.deleteModal.retentionOptions.d90') },
  { value: 180, label: t('admin.systemKnowledge.deleteModal.retentionOptions.d180') },
])

const openDeleteModal = (record: SystemKnowledgeRecord) => {
  deleteTarget.value = record
  deleteRetentionDays.value = 30
  deleteConfirmLoading.value = false
}

const confirmDeleteKnowledge = async () => {
  if (!deleteTarget.value) return
  deleteConfirmLoading.value = true
  try {
    await deleteSystemKnowledge(deleteTarget.value.id, deleteRetentionDays.value)
    Message.success(t('admin.systemKnowledge.deleteSuccess'))
    deleteTarget.value = null
    // 删除后若当前页只剩这一条且不在第一页，回退一页避免空页
    if (records.value.length <= 1 && currentPage.value > 1) {
      currentPage.value -= 1
    }
    await loadList()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.systemKnowledge.deleteFailed')))
  } finally {
    deleteConfirmLoading.value = false
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

// ==================== 库内文档管理抽屉 ====================
const docDrawerVisible = ref(false)
const docDrawerActiveTab = ref<'docs' | 'hitTest'>('docs')
const currentKb = ref<SystemKnowledgeRecord | null>(null)

// 文档列表
const docLoading = ref(false)
const docs = ref<AdminKnowledgeDocument[]>([])
const docTotal = ref(0)
const docPage = ref(1)
const docPageSize = ref(20)
const deletingDocId = ref<string | null>(null)
const docUploading = ref(false)
const uploadPhase = ref<'uploading' | 'polling' | 'success' | 'error'>('uploading')
const uploadDocStatus = ref('')
const uploadSegCount = ref(0)
const uploadErrorMsg = ref('')
let uploadPollTimer: number | null = null
const UPLOAD_POLL_INTERVAL = 1500
const UPLOAD_POLL_TIMEOUT = 120000

const clearUploadPollTimer = () => {
  if (uploadPollTimer !== null) {
    window.clearTimeout(uploadPollTimer)
    uploadPollTimer = null
  }
}

const resetUploadState = () => {
  clearUploadPollTimer()
  docUploading.value = false
  uploadPhase.value = 'uploading'
  uploadDocStatus.value = ''
  uploadSegCount.value = 0
  uploadErrorMsg.value = ''
}

const uploadStatusText = computed(() => {
  const statusKey = uploadDocStatus.value
  if (uploadPhase.value === 'uploading') return t('admin.systemKnowledge.drawer.statusText.uploading')
  if (uploadPhase.value === 'error') {
    return t('admin.systemKnowledge.drawer.statusText.error', {
      message: uploadErrorMsg.value || t('admin.systemKnowledge.drawer.statusText.parseError'),
    })
  }
  if (uploadPhase.value === 'success' || statusKey === 'completed') {
    return t('admin.systemKnowledge.drawer.statusText.completed', { count: uploadSegCount.value })
  }
  if (statusKey === 'waiting') return t('admin.systemKnowledge.drawer.statusText.waiting')
  if (statusKey === 'parsing') return t('admin.systemKnowledge.drawer.statusText.parsing')
  if (statusKey === 'splitting') return t('admin.systemKnowledge.drawer.statusText.splitting')
  if (statusKey === 'indexing') {
    if (uploadSegCount.value > 0) {
      return t('admin.systemKnowledge.drawer.statusText.indexingSegmented', { count: uploadSegCount.value })
    }
    return t('admin.systemKnowledge.drawer.statusText.indexing')
  }
  return t('admin.systemKnowledge.drawer.statusText.processing')
})

const uploadSteps = computed(() => {
  const labels = {
    upload: t('admin.systemKnowledge.drawer.steps.upload'),
    parse: t('admin.systemKnowledge.drawer.steps.parse'),
    segment: t('admin.systemKnowledge.drawer.steps.segment'),
    vectorize: t('admin.systemKnowledge.drawer.steps.vectorize'),
    complete: t('admin.systemKnowledge.drawer.steps.complete'),
  }
  if (uploadPhase.value === 'uploading') {
    return [
      { key: 'upload', state: 'active', label: labels.upload },
      { key: 'parse', state: 'pending', label: labels.parse },
      { key: 'segment', state: 'pending', label: labels.segment },
      { key: 'vectorize', state: 'pending', label: labels.vectorize },
      { key: 'complete', state: 'pending', label: labels.complete },
    ]
  }
  if (uploadPhase.value === 'error') {
    return [
      { key: 'upload', state: 'done', label: labels.upload },
      { key: 'parse', state: 'failed', label: labels.parse },
      { key: 'segment', state: 'pending', label: labels.segment },
      { key: 'vectorize', state: 'pending', label: labels.vectorize },
      { key: 'complete', state: 'pending', label: labels.complete },
    ]
  }
  const segKnown = uploadSegCount.value > 0
  const statusKey = uploadDocStatus.value
  return [
    { key: 'upload', state: 'done', label: labels.upload },
    {
      key: 'parse',
      state: segKnown || statusKey === 'indexing' ? 'done' : 'active',
      label: labels.parse,
    },
    {
      key: 'segment',
      state: segKnown ? 'done' : statusKey === 'indexing' ? 'active' : 'pending',
      label: labels.segment,
    },
    {
      key: 'vectorize',
      state: uploadPhase.value === 'success' ? 'done' : segKnown && statusKey === 'indexing' ? 'active' : 'pending',
      label: labels.vectorize,
    },
    { key: 'complete', state: uploadPhase.value === 'success' ? 'done' : 'pending', label: labels.complete },
  ]
})

const handleDocUploadChange = (_fileList: FileItem[], fileItem: FileItem) => {
  const file = fileItem?.file
  if (file) void handleUploadDoc(file)
}

const pollDocumentStatus = async (knowledgeBaseId: string, documentId: string, startTime: number) => {
  if (Date.now() - startTime > UPLOAD_POLL_TIMEOUT) {
    uploadPhase.value = 'error'
    uploadErrorMsg.value = t('admin.systemKnowledge.drawer.statusText.timeout')
    docUploading.value = false
    return
  }
  try {
    const doc = await getAdminKnowledgeDocument(knowledgeBaseId, documentId)
    uploadDocStatus.value = doc.status
    uploadSegCount.value = doc.segment_count ?? 0
    if (doc.status === 'completed') {
      uploadPhase.value = 'success'
      Message.success(t('admin.systemKnowledge.drawer.statusText.completed', { count: doc.segment_count ?? 0 }))
      docUploading.value = false
      await loadDocs()
      return
    }
    if (doc.status === 'error') {
      uploadPhase.value = 'error'
      uploadErrorMsg.value = doc.error || t('admin.systemKnowledge.drawer.statusText.parseError')
      docUploading.value = false
      Message.error(uploadErrorMsg.value)
      await loadDocs()
      return
    }
    uploadPhase.value = 'polling'
    uploadPollTimer = window.setTimeout(() => {
      void pollDocumentStatus(knowledgeBaseId, documentId, startTime)
    }, UPLOAD_POLL_INTERVAL)
  } catch {
    uploadPhase.value = 'polling'
    uploadPollTimer = window.setTimeout(() => {
      void pollDocumentStatus(knowledgeBaseId, documentId, startTime)
    }, UPLOAD_POLL_INTERVAL)
  }
}

const handleUploadDoc = async (file: File) => {
  if (!currentKb.value || docUploading.value) return
  resetUploadState()
  docUploading.value = true
  uploadPhase.value = 'uploading'
  const knowledgeBaseId = currentKb.value.id
  try {
    const response = await uploadAdminKnowledgeDocument(knowledgeBaseId, file)
    const documentId = response.data?.id
    if (!documentId) {
      uploadPhase.value = 'error'
      uploadErrorMsg.value = t('admin.systemKnowledge.drawer.statusText.missingId')
      docUploading.value = false
      Message.error(uploadErrorMsg.value)
      return
    }
    uploadPhase.value = 'polling'
    await pollDocumentStatus(knowledgeBaseId, documentId, Date.now())
  } catch (error) {
    uploadPhase.value = 'error'
    uploadErrorMsg.value = getErrorMessage(error, t('admin.systemKnowledge.drawer.uploadFailed'))
    docUploading.value = false
    Message.error(uploadErrorMsg.value)
  }
}

const docStatusLabel = (status: string) => {
  const key = `admin.systemKnowledge.drawer.statuses.${status}`
  const label = t(key)
  return label === key ? status : label
}

const openDocDrawer = (record: SystemKnowledgeRecord) => {
  currentKb.value = record
  docDrawerVisible.value = true
  docDrawerActiveTab.value = 'docs'
  docPage.value = 1
  docs.value = []
  docTotal.value = 0
  void loadDocs()
}

const closeDocDrawer = () => {
  docDrawerVisible.value = false
  currentKb.value = null
  resetUploadState()
}

const loadDocs = async () => {
  if (!currentKb.value) return
  docLoading.value = true
  try {
    const result = await listAdminKnowledgeDocuments(currentKb.value.id, {
      current_page: docPage.value,
      page_size: docPageSize.value,
      search_word: '',
    })
    docs.value = result.items || []
    docTotal.value = result.total_record ?? result.total ?? 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.systemKnowledge.drawer.loadFailed')))
  } finally {
    docLoading.value = false
  }
}

const handleDocPageChange = (page: number) => {
  docPage.value = page
  void loadDocs()
}

// 新建/编辑文本文档弹窗
const docModalVisible = ref(false)
const docModalMode = ref<'create' | 'edit'>('create')
const docModalTarget = ref<AdminKnowledgeDocument | null>(null)
const docForm = ref({ name: '', content: '' })
const docModalLoading = ref(false)
const docModalContentLoading = ref(false)

const openCreateDocModal = () => {
  docModalMode.value = 'create'
  docModalTarget.value = null
  docForm.value = { name: '', content: '' }
  docModalVisible.value = true
}

const openEditDocModal = async (doc: AdminKnowledgeDocument) => {
  if (!currentKb.value) return
  docModalMode.value = 'edit'
  docModalTarget.value = doc
  docForm.value = { name: doc.name, content: '' }
  docModalVisible.value = true
  // 异步加载分段内容，拼接为可编辑的原文
  docModalContentLoading.value = true
  try {
    let contentParts: string[] = []
    let page = 1
    const pageSize = 50
    let total = Number.POSITIVE_INFINITY
    while (contentParts.length < total) {
      const data = await listAdminDocumentSegments(currentKb.value.id, doc.id, page, pageSize)
      const items = data.list || []
      if (items.length === 0) break
      total = data.paginator?.total_record ?? items.length
      contentParts = contentParts.concat(
        [...items]
          .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
          .map((s) => s.content),
      )
      page += 1
    }
    docForm.value.content = contentParts.join('\n\n')
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.systemKnowledge.drawer.docContentLoadFailed')))
  } finally {
    docModalContentLoading.value = false
  }
}

const handleDocModalSubmit = async () => {
  if (!currentKb.value) return
  const name = docForm.value.name.trim()
  if (!name) {
    Message.error(t('admin.systemKnowledge.drawer.docNameRequired'))
    return
  }
  if (!docForm.value.content.trim()) {
    Message.error(t('admin.systemKnowledge.drawer.docContentRequired'))
    return
  }
  docModalLoading.value = true
  try {
    if (docModalMode.value === 'create') {
      await createAdminTextDocument(currentKb.value.id, name, docForm.value.content)
      Message.success(t('admin.systemKnowledge.drawer.createDocSuccess'))
    } else if (docModalTarget.value) {
      await updateAdminTextDocument(currentKb.value.id, docModalTarget.value.id, name, docForm.value.content)
      Message.success(t('admin.systemKnowledge.drawer.updateDocSuccess'))
    }
    docModalVisible.value = false
    await loadDocs()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.systemKnowledge.drawer.saveDocFailed')))
  } finally {
    docModalLoading.value = false
  }
}

const handleDeleteDoc = async (retentionDays: number) => {
  if (!currentKb.value || !docDeleteTarget.value) return
  deletingDocId.value = docDeleteTarget.value.id
  try {
    await deleteAdminKnowledgeDocument(
      currentKb.value.id,
      docDeleteTarget.value.id,
      retentionDays,
    )
    Message.success(t('admin.systemKnowledge.drawer.deleteDocSuccess'))
    docDeleteTarget.value = null
    await loadDocs()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.systemKnowledge.drawer.deleteDocFailed')))
  } finally {
    deletingDocId.value = null
  }
}

const docDeleteTarget = ref<AdminKnowledgeDocument | null>(null)

const openDocDeleteModal = (doc: AdminKnowledgeDocument) => {
  docDeleteTarget.value = doc
}

// 命中测试
const hitQuery = ref('')
const hitStrategy = ref('semantic')
const hitK = ref(5)
const hitTesting = ref(false)
const hitResults = ref<AdminHitTestItem[]>([])

const strategyOptions = computed(() => [
  { value: 'semantic', label: 'Semantic' },
  { value: 'fulltext', label: 'Fulltext' },
  { value: 'hybrid', label: 'Hybrid' },
])

const runHitTest = async () => {
  if (!currentKb.value || !hitQuery.value.trim()) return
  hitTesting.value = true
  try {
    const result = await hitTestAdminKnowledge(currentKb.value.id, {
      query: hitQuery.value.trim(),
      retrieval_strategy: hitStrategy.value,
      k: hitK.value,
      score: 0,
    })
    hitResults.value = Array.isArray(result) ? result : []
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.systemKnowledge.drawer.loadFailed')))
  } finally {
    hitTesting.value = false
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
  { value: 'agent', label: t('admin.systemKnowledge.prompt.categories.agent') },
  { value: 'assistant', label: t('admin.systemKnowledge.prompt.categories.assistant') },
  { value: 'memory', label: t('admin.systemKnowledge.prompt.categories.memory') },
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
 * 删除系统内置提示词（进入回收站，选择留存时间；删除后运行时回退 YAML 默认）。
 */
const promptDeleteTarget = ref<PromptTemplateItem | null>(null)
const promptDeleteRetentionDays = ref(30)
const promptDeleteLoading = ref(false)

const openPromptDeleteModal = (item: PromptTemplateItem) => {
  promptDeleteTarget.value = item
  promptDeleteRetentionDays.value = 30
  promptDeleteLoading.value = false
}

const confirmDeletePrompt = async () => {
  if (!promptDeleteTarget.value) return
  promptDeleteLoading.value = true
  try {
    const payload = { retention_days: promptDeleteRetentionDays.value }
    await del<BaseResponse<unknown>>(`/admin/prompt-templates/${promptDeleteTarget.value.prompt_key}`, {
      body: payload,
    })
    Message.success(t('admin.systemKnowledge.prompt.deleteSuccess'))
    promptDeleteTarget.value = null
    await loadPromptTemplates()
  } catch (e) {
    Message.error(getErrorMessage(e, t('admin.systemKnowledge.prompt.deleteFailed')))
  } finally {
    promptDeleteLoading.value = false
  }
}

/**
 * 切换系统内置提示词启停状态。
 * 停用后运行时会回退到 YAML 内置默认文本；重新启用恢复可管理版本。
 */
const handleTogglePromptEnabled = async (tp: PromptTemplateItem, enabled: boolean) => {
  try {
    await updatePromptTemplate(tp.prompt_key, { enabled })
    tp.enabled = enabled
    Message.success(
      enabled
        ? t('admin.systemKnowledge.prompt.enableSuccess')
        : t('admin.systemKnowledge.prompt.disableSuccess'),
    )
  } catch (e) {
    Message.error(getErrorMessage(e, t('common.saveFailed')))
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

onBeforeUnmount(() => {
  clearUploadPollTimer()
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
                      <!-- 生效状态：明确标识哪个知识库对 Agent 实际生效 -->
                      <a-tag
                        size="small"
                        :color="record.enabled ? 'green' : 'gray'"
                        class="!text-[11px]"
                      >
                        {{ record.enabled ? t('admin.systemKnowledge.effective') : t('admin.systemKnowledge.inactive') }}
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
                  <a-tag v-if="record.document_count !== undefined" size="small" color="arcoblue">
                    {{ t('admin.systemKnowledge.stats.documents', { count: record.document_count }) }}
                  </a-tag>
                  <a-tag v-if="record.character_count !== undefined" size="small" color="gray">
                    {{ t('admin.systemKnowledge.stats.characters', { count: record.character_count }) }}
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
                  class="flex items-center gap-1.5 mt-2.5 pt-2 border-t border-gray-100 flex-wrap"
                >
                  <a-button size="mini" type="primary" @click="openDocDrawer(record)">
                    {{ t('admin.systemKnowledge.stats.manageBtn') }}
                  </a-button>
                  <a-button size="mini" type="outline" @click="openEditModal(record)">
                    {{ t('admin.systemKnowledge.editBtn') }}
                  </a-button>
                  <a-button size="mini" status="danger" @click="openDeleteModal(record)">
                    {{ t('admin.systemKnowledge.deleteBtn') }}
                  </a-button>
                </div>
                <div v-else class="mt-2.5 pt-2 border-t border-gray-100">
                  <a-button size="mini" type="primary" @click="openDocDrawer(record)">
                    {{ t('admin.systemKnowledge.stats.manageBtn') }}
                  </a-button>
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
                    <a-switch
                      v-if="canWrite && tp.enabled !== undefined"
                      v-model="tp.enabled"
                      size="small"
                      :checked-text="t('admin.systemKnowledge.enabled')"
                      :un-checked-text="t('admin.systemKnowledge.disabled')"
                      @change="(val: boolean | string | number) => handleTogglePromptEnabled(tp, Boolean(val))"
                    />
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
                  <a-button size="mini" status="danger" @click="openPromptDeleteModal(tp)">
                    {{ t('admin.systemKnowledge.prompt.deleteBtn') }}
                  </a-button>
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
          : t('admin.systemKnowledge.modal.editTitleWithName', { name: editingRecord?.name || '' })
      "
      :confirm-loading="submitting"
      @ok="handleSubmit"
    >
      <div
        v-if="modalMode === 'edit' && editingRecord"
        class="mb-4 flex items-center gap-2 flex-wrap text-sm"
      >
        <a-tag :color="editingRecord.enabled ? 'green' : 'gray'">
          {{ editingRecord.enabled ? t('admin.systemKnowledge.effective') : t('admin.systemKnowledge.inactive') }}
        </a-tag>
        <span class="text-slate-500">
          {{ editingRecord.enabled ? t('admin.systemKnowledge.toggleEnabledOn') : t('admin.systemKnowledge.toggleEnabledOff') }}
        </span>
      </div>
      <a-form :model="formModel" layout="vertical">
        <a-form-item :label="t('admin.systemKnowledge.modal.nameLabel')" required>
          <a-input
            v-model="formModel.name"
            :placeholder="t('admin.systemKnowledge.modal.namePlaceholder')"
          />
          <template #extra>{{ t('admin.systemKnowledge.modal.nameHint') }}</template>
        </a-form-item>
        <a-form-item :label="t('admin.systemKnowledge.modal.descriptionLabel')">
          <a-textarea
            v-model="formModel.description"
            :placeholder="t('admin.systemKnowledge.modal.descriptionPlaceholder')"
            :auto-size="{ minRows: 3, maxRows: 6 }"
          />
          <template #extra>{{ t('admin.systemKnowledge.modal.descriptionHint') }}</template>
        </a-form-item>
        <a-form-item :label="t('admin.systemKnowledge.modal.visibilityLabel')">
          <a-select v-model="formModel.visibility_scope" :options="visibilityOptions" />
          <template #extra>{{ t('admin.systemKnowledge.modal.visibilityHint') }}</template>
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
        <a-form layout="vertical" :model="{}">
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

    <!-- ==================== 知识库删除留存时间弹窗 ==================== -->
    <a-modal
      :visible="deleteTarget !== null"
      :title="deleteTarget ? t('admin.systemKnowledge.deleteModal.title', { name: deleteTarget.name }) : ''"
      :confirm-loading="deleteConfirmLoading"
      :ok-text="t('admin.systemKnowledge.deleteModal.confirmBtn')"
      :cancel-text="t('admin.systemKnowledge.deleteModal.cancelBtn')"
      @ok="confirmDeleteKnowledge"
      @cancel="deleteTarget = null"
    >
      <div class="space-y-4">
        <p class="text-sm text-slate-500">{{ t('admin.systemKnowledge.deleteModal.retentionHint') }}</p>
        <div class="flex items-center gap-3">
          <span class="text-sm text-slate-600 shrink-0">
            {{ t('admin.systemKnowledge.deleteModal.retentionLabel') }}
          </span>
          <a-radio-group v-model="deleteRetentionDays" type="button" class="flex-wrap">
            <a-radio
              v-for="opt in retentionOptions"
              :key="opt.value"
              :value="opt.value"
            >
              {{ opt.label }}
            </a-radio>
          </a-radio-group>
        </div>
      </div>
    </a-modal>

    <!-- ==================== 提示词删除留存时间弹窗 ==================== -->
    <a-modal
      :visible="promptDeleteTarget !== null"
      :title="promptDeleteTarget ? t('admin.systemKnowledge.deleteModal.title', { name: promptDeleteTarget.name }) : ''"
      :confirm-loading="promptDeleteLoading"
      :ok-text="t('admin.systemKnowledge.deleteModal.confirmBtn')"
      :cancel-text="t('admin.systemKnowledge.deleteModal.cancelBtn')"
      @ok="confirmDeletePrompt"
      @cancel="promptDeleteTarget = null"
    >
      <div class="space-y-4">
        <p class="text-sm text-slate-500">
          {{ t('admin.systemKnowledge.prompt.deleteConfirm') }}
        </p>
        <div class="flex items-center gap-3">
          <span class="text-sm text-slate-600 shrink-0">
            {{ t('admin.systemKnowledge.deleteModal.retentionLabel') }}
          </span>
          <a-radio-group v-model="promptDeleteRetentionDays" type="button" class="flex-wrap">
            <a-radio
              v-for="opt in retentionOptions"
              :key="opt.value"
              :value="opt.value"
            >
              {{ opt.label }}
            </a-radio>
          </a-radio-group>
        </div>
      </div>
    </a-modal>

    <!-- ==================== 库内文档管理抽屉 ==================== -->
    <a-drawer
      :visible="docDrawerVisible"
      :width="720"
      :title="t('admin.systemKnowledge.drawer.title')"
      :footer="false"
      unmount-on-close
      @cancel="closeDocDrawer"
    >
      <template v-if="currentKb">
        <div class="flex items-center gap-2 mb-4 flex-wrap">
          <span class="font-semibold text-gray-900">{{ currentKb.name }}</span>
          <a-tag size="small" :color="currentKb.enabled ? 'green' : 'gray'">
            {{ currentKb.enabled ? t('admin.systemKnowledge.enabled') : t('admin.systemKnowledge.disabled') }}
          </a-tag>
        </div>

        <a-tabs v-model:active-key="docDrawerActiveTab" type="rounded">
          <!-- 文档列表 -->
          <a-tab-pane key="docs" :title="t('admin.systemKnowledge.drawer.docTab')">
            <div class="space-y-3 pt-3">
              <div class="flex items-center justify-between gap-2">
                <span class="text-xs text-slate-400">
                  {{ t('admin.systemKnowledge.total', { count: docTotal }) }}
                </span>
                <div class="flex items-center gap-2">
                  <a-button size="mini" :loading="docLoading" @click="loadDocs">
                    {{ t('admin.systemKnowledge.drawer.refreshBtn') }}
                  </a-button>
                  <a-button size="mini" type="primary" @click="openCreateDocModal">
                    {{ t('admin.systemKnowledge.drawer.createDocBtn') }}
                  </a-button>
                  <a-upload
                    :show-file-list="false"
                    :auto-upload="false"
                    accept=".txt,.md,.pdf,.docx,.csv,.json,.html,.xlsx"
                    :disabled="docUploading"
                    @change="handleDocUploadChange"
                  >
                    <a-button size="mini" :loading="docUploading">
                      {{ t('admin.systemKnowledge.drawer.uploadBtn') }}
                    </a-button>
                  </a-upload>
                </div>
              </div>

              <!-- 上传状态监测 -->
              <div v-if="docUploading" class="rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2.5">
                <div class="mb-2 flex items-center gap-2">
                  <a-spin v-if="uploadPhase !== 'error'" :size="14" />
                  <icon-close-circle v-else class="shrink-0 text-red-500" />
                  <span class="text-xs font-medium text-gray-700">{{ uploadStatusText }}</span>
                </div>
                <ul class="space-y-1.5">
                  <li
                    v-for="step in uploadSteps"
                    :key="step.key"
                    class="flex items-center gap-2 text-xs"
                  >
                    <icon-check-circle v-if="step.state === 'done'" class="shrink-0 text-green-500" />
                    <a-spin v-else-if="step.state === 'active'" :size="12" />
                    <icon-close-circle v-else-if="step.state === 'failed'" class="shrink-0 text-red-500" />
                    <span v-else class="inline-block h-3 w-3 shrink-0 rounded-full border border-slate-300" />
                    <span
                      :class="step.state === 'pending' ? 'text-slate-400' : step.state === 'failed' ? 'text-red-600' : 'text-gray-700'"
                    >
                      {{ step.label }}
                      <span v-if="step.key === 'segment' && uploadSegCount > 0" class="text-slate-400">
                        {{ t('admin.systemKnowledge.drawer.steps.segmentCount', { count: uploadSegCount }) }}
                      </span>
                    </span>
                  </li>
                </ul>
              </div>

              <a-table
                :data="docs"
                :loading="docLoading"
                :pagination="false"
                row-key="id"
                size="small"
                class="rounded-lg border border-slate-200 overflow-hidden"
              >
                <template #columns>
                  <a-table-column :title="t('admin.systemKnowledge.drawer.docName')" data-index="name">
                    <template #cell="{ record }">
                      <div class="text-sm text-gray-800 truncate max-w-[260px]">{{ record.name }}</div>
                    </template>
                  </a-table-column>
                  <a-table-column :title="t('admin.systemKnowledge.drawer.docStatus')" data-index="status" :width="90">
                    <template #cell="{ record }">
                      <a-tag size="small" :color="record.status === 'completed' ? 'green' : record.status === 'error' ? 'red' : 'gold'">
                        {{ docStatusLabel(record.status) }}
                      </a-tag>
                    </template>
                  </a-table-column>
                  <a-table-column :title="t('admin.systemKnowledge.drawer.docCharacters')" data-index="segment_character_count" :width="100">
                    <template #cell="{ record }">
                      <span class="text-xs text-gray-500">
                        {{ record.segment_character_count ?? record.character_count ?? 0 }}
                      </span>
                    </template>
                  </a-table-column>
                  <a-table-column :title="t('admin.systemKnowledge.drawer.docSegments')" data-index="segment_count" :width="90">
                    <template #cell="{ record }">
                      <span class="text-xs text-gray-500">{{ record.segment_count ?? '-' }}</span>
                    </template>
                  </a-table-column>
                  <a-table-column :title="t('admin.systemKnowledge.drawer.docUpdatedAt')" data-index="updated_at" :width="150">
                    <template #cell="{ record }">
                      <span class="text-xs text-gray-500">{{ formatTimestampShort(record.updated_at) }}</span>
                    </template>
                  </a-table-column>
                  <a-table-column :title="t('admin.systemKnowledge.drawer.docActions')" :width="120" fixed="right">
                    <template #cell="{ record }">
                      <div class="flex items-center gap-1">
                        <a-button
                          size="mini"
                          type="outline"
                          :disabled="docUploading"
                          @click="openEditDocModal(record)"
                        >
                          {{ t('admin.systemKnowledge.editBtn') }}
                        </a-button>
                        <a-button
                          size="mini"
                          status="danger"
                          :loading="deletingDocId === record.id"
                          @click="openDocDeleteModal(record)"
                        >
                          {{ t('common.actions.delete') }}
                        </a-button>
                      </div>
                    </template>
                  </a-table-column>
                </template>
                <template #empty>
                  <div class="py-10 text-center text-sm text-slate-400">
                    {{ t('admin.systemKnowledge.drawer.empty') }}
                  </div>
                </template>
              </a-table>

              <a-pagination
                v-if="docTotal > 0"
                :current="docPage"
                :page-size="docPageSize"
                :total="docTotal"
                size="small"
                show-total
                @change="handleDocPageChange"
              />

              <!-- 文档删除确认弹窗（进入回收站 + 选择留存天数） -->
              <RecycleBinDeleteModal
                :visible="docDeleteTarget !== null"
                :title="t('common.actions.delete')"
                :resource-name="docDeleteTarget?.name"
                :loading="deletingDocId !== null"
                @update:visible="(v) => { if (!v) docDeleteTarget = null }"
                @confirm="handleDeleteDoc"
              >
                <p class="text-sm text-slate-500">
                  {{ t('admin.systemKnowledge.drawer.deleteDocConfirm') }}
                </p>
              </RecycleBinDeleteModal>

              <!-- 新建/编辑文本文档弹窗 -->
              <a-modal
                :visible="docModalVisible"
                :title="
                  docModalMode === 'create'
                    ? t('admin.systemKnowledge.drawer.createDocTitle')
                    : t('admin.systemKnowledge.drawer.updateDocTitle')
                "
                :confirm-loading="docModalLoading"
                :ok-text="t('common.actions.save')"
                :cancel-text="t('common.actions.cancel')"
                @ok="handleDocModalSubmit"
                @cancel="docModalVisible = false"
              >
                <div v-if="docModalContentLoading" class="text-sm text-slate-400 py-4 text-center">
                  {{ t('admin.systemKnowledge.drawer.docContentLoading') }}
                </div>
                <div v-else class="space-y-3">
                  <a-form-item :label="t('admin.systemKnowledge.drawer.docName')" required>
                    <a-input
                      v-model="docForm.name"
                      :placeholder="t('admin.systemKnowledge.drawer.docNamePlaceholder')"
                    />
                  </a-form-item>
                  <a-form-item :label="t('admin.systemKnowledge.drawer.docContent')" required>
                    <a-textarea
                      v-model="docForm.content"
                      :placeholder="t('admin.systemKnowledge.drawer.docContentPlaceholder')"
                      :auto-size="{ minRows: 10, maxRows: 18 }"
                    />
                  </a-form-item>
                </div>
              </a-modal>
            </div>
          </a-tab-pane>

          <!-- 命中测试 -->
          <a-tab-pane key="hitTest" :title="t('admin.systemKnowledge.drawer.hitTestTab')">
            <div class="space-y-4 pt-3">
              <div class="space-y-3">
                <div>
                  <div class="text-sm text-slate-600 mb-1">{{ t('admin.systemKnowledge.hitTest.queryLabel') }}</div>
                  <a-textarea
                    v-model="hitQuery"
                    :placeholder="t('admin.systemKnowledge.hitTest.queryPlaceholder')"
                    :auto-size="{ minRows: 2, maxRows: 4 }"
                  />
                </div>
                <div class="flex flex-wrap items-center gap-3">
                  <div>
                    <div class="text-sm text-slate-600 mb-1">{{ t('admin.systemKnowledge.hitTest.strategyLabel') }}</div>
                    <a-select v-model="hitStrategy" class="w-40" :options="strategyOptions" />
                  </div>
                  <div>
                    <div class="text-sm text-slate-600 mb-1">{{ t('admin.systemKnowledge.hitTest.topKLabel') }}</div>
                    <a-input-number v-model="hitK" :min="1" :max="10" class="w-24" />
                  </div>
                  <div class="self-end">
                    <a-button type="primary" :loading="hitTesting" @click="runHitTest">
                      {{ t('admin.systemKnowledge.hitTest.testBtn') }}
                    </a-button>
                  </div>
                </div>
              </div>

              <div>
                <div class="text-sm font-medium text-slate-700 mb-2">
                  {{ t('admin.systemKnowledge.hitTest.resultTitle') }}
                </div>
                <div v-if="hitResults.length === 0" class="text-sm text-slate-400 py-6 text-center rounded-lg border border-dashed border-slate-300">
                  {{ t('admin.systemKnowledge.hitTest.emptyResult') }}
                </div>
                <div v-else class="space-y-2">
                  <div
                    v-for="(item, idx) in hitResults"
                    :key="item.id"
                    class="rounded-lg border border-slate-200 p-3"
                  >
                    <div class="flex items-center justify-between gap-2 mb-1">
                      <span class="text-xs font-medium text-gray-700 truncate">
                        {{ idx + 1 }}. {{ item.document?.name || '-' }}
                      </span>
                      <a-tag size="small" color="arcoblue">
                        {{ t('admin.systemKnowledge.hitTest.score') }}: {{ (item.score ?? 0).toFixed(4) }}
                      </a-tag>
                    </div>
                    <div class="text-xs text-gray-500 line-clamp-3 whitespace-pre-wrap">
                      {{ item.content }}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </a-tab-pane>
        </a-tabs>
      </template>
    </a-drawer>
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
