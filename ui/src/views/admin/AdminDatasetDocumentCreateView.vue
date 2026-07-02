<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { type FileItem, Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useCreateDocuments, useGetDocumentsStatus } from '@/hooks/use-dataset'
import { useUploadFile } from '@/hooks/use-upload-file'
import type { CreateDocumentsRequest, GetDocumentsStatusResponse } from '@/models/dataset'
import { unescapeString } from '@/utils/helper'

type DocumentProcessType = 'automatic' | 'custom'

type CustomRuleForm = {
  separators: string[]
  chunk_size: number
  chunk_overlap: number
  pre_process_rules: string[]
}

type CreateDocumentsForm = {
  file_list: FileItem[]
  process_type: DocumentProcessType
  rule: CustomRuleForm
}

type UploadCustomRequestOption = {
  fileItem: FileItem
  onSuccess: (response?: unknown) => void
  onError: (error?: Error) => void
}

type UploadFileResponsePayload = {
  id?: string
}

const DEFAULT_RULE_SEPARATORS = [
  '\\n\\n',
  '\\n',
  '。|！|？',
  '\\.\\s|\\!\\s|\\?\\s',
  '；|;\\s',
  '，|,\\s',
  ' ',
  '',
] as const
const DEFAULT_CHUNK_SIZE = 500
const DEFAULT_CHUNK_OVERLAP = 50

const route = useRoute()
const { t } = useI18n()
const {
  loading: createDocumentsLoading,
  create_documents_result,
  handleCreateDocuments,
} = useCreateDocuments()
const { documents_status_result, loadDocumentsStatus } = useGetDocumentsStatus()
const { handleUploadFile } = useUploadFile()
const currentStep = ref(1)
const documents = ref<GetDocumentsStatusResponse['data']>([])
const createDocumentsForm = ref<CreateDocumentsForm>({
  file_list: [],
  process_type: 'automatic',
  rule: {
    separators: [...DEFAULT_RULE_SEPARATORS],
    chunk_size: DEFAULT_CHUNK_SIZE,
    chunk_overlap: DEFAULT_CHUNK_OVERLAP,
    pre_process_rules: [],
  },
})
let timer: ReturnType<typeof setInterval> | null = null
let batch = ''
let fetchCount = 0

/**
 * 解析当前后台知识库路由中的数据集标识，供创建页壳展示。
 */
const datasetId = String(route.params.dataset_id ?? '')

/**
 * 从上传组件的响应对象中提取文件标识，供步骤校验复用。
 */
const getUploadFileId = (fileItem: FileItem): string => {
  const response = fileItem.response as UploadFileResponsePayload | undefined
  return response?.id ? String(response.id) : ''
}

/**
 * 构造自动分段模式的默认处理规则，保持与后端默认规则一致。
 */
const buildAutomaticRule = (): CreateDocumentsRequest['rule'] => {
  return {
    pre_process_rules: [
      { id: 'remove_extra_space', enabled: true },
      { id: 'remove_url_and_email', enabled: true },
    ],
    segment: {
      separators: DEFAULT_RULE_SEPARATORS.map((separator) => unescapeString(separator)),
      chunk_size: DEFAULT_CHUNK_SIZE,
      chunk_overlap: DEFAULT_CHUNK_OVERLAP,
    },
  }
}

/**
 * 基于当前自定义表单状态构造处理规则，供创建请求复用。
 */
const buildCustomRule = (): CreateDocumentsRequest['rule'] => {
  const enabledRules = new Set(createDocumentsForm.value.rule.pre_process_rules)

  return {
    pre_process_rules: [
      {
        id: 'remove_extra_space',
        enabled: enabledRules.has('remove_extra_space'),
      },
      {
        id: 'remove_url_and_email',
        enabled: enabledRules.has('remove_url_and_email'),
      },
    ],
    segment: {
      separators: createDocumentsForm.value.rule.separators.map((separator) =>
        unescapeString(separator),
      ),
      chunk_size: createDocumentsForm.value.rule.chunk_size,
      chunk_overlap: createDocumentsForm.value.rule.chunk_overlap,
    },
  }
}

/**
 * 构造文档创建请求体，兼容自动与自定义分段模式。
 */
const buildCreateRequest = (): CreateDocumentsRequest => {
  return {
    upload_file_ids: createDocumentsForm.value.file_list.map((fileItem) => getUploadFileId(fileItem)),
    process_type: createDocumentsForm.value.process_type,
    rule:
      createDocumentsForm.value.process_type === 'custom'
        ? buildCustomRule()
        : buildAutomaticRule(),
  }
}

/**
 * 将状态查询 hook 的结果同步到页面展示数据，避免模板直接依赖 hook 内部引用。
 */
const syncDocumentsStatus = () => {
  documents.value = documents_status_result.value as GetDocumentsStatusResponse['data']
}

/**
 * 判断当前批处理状态是否已经满足停止轮询条件。
 */
const shouldStopPolling = () => {
  if (!batch) return true
  if (fetchCount >= 30) return true
  if (documents.value.length === 0) return false

  return documents.value.every((document) =>
    ['completed', 'error'].includes(String(document.status)),
  )
}

/**
 * 停止后台导入处理状态轮询，避免页面切换后残留定时器。
 */
const stopTimer = () => {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

/**
 * 启动后台导入处理状态轮询，并在每次轮询中复用统一的查询逻辑。
 */
const startTimer = () => {
  stopTimer()
  if (shouldStopPolling()) return

  timer = setInterval(() => {
    void fetchDocumentsStatus()
  }, 5000)
}

/**
 * 拉取当前批处理的文档状态，并在满足完成条件后主动收口轮询。
 */
const fetchDocumentsStatus = async () => {
  if (!datasetId || !batch) {
    stopTimer()
    return
  }

  fetchCount += 1
  await loadDocumentsStatus(datasetId, batch)
  syncDocumentsStatus()

  if (shouldStopPolling()) stopTimer()
}

/**
 * 将文档处理状态格式化为页面可读文本，覆盖处理中、完成和失败场景。
 */
const getDocumentStatusText = (document: GetDocumentsStatusResponse['data'][number]) => {
  if (document.status === 'error') {
    return t('admin.datasetDocumentImport.processingError')
  }

  if (document.status === 'completed') {
    return t('admin.datasetDocumentImport.processingCompleted')
  }

  if (document.segment_count === 0) {
    return '0.00%'
  }

  return ((document.completed_segment_count / document.segment_count) * 100).toFixed(2) + '%'
}

/**
 * 使用既有上传 hook 处理后台导入页的文件上传，并将返回的文件标识回填给上传组件。
 */
const handleCustomRequest = (option: UploadCustomRequestOption) => {
  const { fileItem, onSuccess, onError } = option

  const uploadTask = async () => {
    try {
      if (!fileItem.file) {
        onError(new Error(t('admin.datasetDocumentImport.invalidFile')))
        return
      }

      const response = await handleUploadFile(fileItem.file as File)
      const fileId = response?.data?.id

      if (!fileId) {
        onError(new Error(t('admin.datasetDocumentImport.uploadMissingId')))
        return
      }

      onSuccess({ id: fileId })
    } catch (error: unknown) {
      onError(
        error instanceof Error
          ? error
          : new Error(t('admin.datasetDocumentImport.uploadMissingId')),
      )
    }
  }

  uploadTask()
  return { abort: () => {} }
}

/**
 * 更新指定索引的分隔符输入值，保持自定义规则数组可编辑。
 */
const updateSeparator = (index: number, value: string) => {
  createDocumentsForm.value.rule.separators[index] = value
}

/**
 * 提交当前导入表单的创建请求，并在成功后进入处理状态步骤。
 */
const submitCreateDocuments = async () => {
  await handleCreateDocuments(datasetId, buildCreateRequest())
  batch = String(create_documents_result.value.batch ?? '')
  fetchCount = 0
  await fetchDocumentsStatus()
  currentStep.value = 3
  startTimer()
}

/**
 * 返回上传步骤，便于重新调整文件列表。
 */
const previousStep = () => {
  currentStep.value = 1
}

/**
 * 驱动后台导入流程，仅在第一步进入规则设置，在第二步提交创建请求。
 */
const nextStep = async () => {
  if (currentStep.value === 2) {
    await submitCreateDocuments()
    return
  }

  if (currentStep.value !== 1) return

  if (createDocumentsForm.value.file_list.length === 0) {
    Message.error(t('admin.datasetDocumentImport.uploadRequired'))
    return
  }

  const isUploaded = createDocumentsForm.value.file_list.every(
    (fileItem) => getUploadFileId(fileItem) !== '',
  )
  if (!isUploaded) {
    Message.warning(t('admin.datasetDocumentImport.uploadingWarning'))
    return
  }

  currentStep.value = 2
}

onUnmounted(() => {
  stopTimer()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex items-center gap-4">
      <router-link
        :to="{ name: 'admin-dataset-documents', params: { dataset_id: datasetId } }"
      >
        <a-button type="text">{{ t('admin.datasetDocumentImport.back') }}</a-button>
      </router-link>
      <div>
        <h1 class="text-2xl font-semibold text-slate-900">
          {{ t('admin.datasetDocumentImport.title') }}
        </h1>
        <p class="text-sm text-slate-500">
          {{ t('admin.datasetDocumentImport.subtitle', { datasetId }) }}
        </p>
      </div>
    </div>

    <a-steps :current="currentStep">
      <a-step>{{ t('admin.datasetDocumentImport.steps.upload') }}</a-step>
      <a-step>{{ t('admin.datasetDocumentImport.steps.segment') }}</a-step>
      <a-step>{{ t('admin.datasetDocumentImport.steps.process') }}</a-step>
    </a-steps>

    <div class="rounded-2xl border border-slate-200 bg-white p-6">
      <div v-if="currentStep === 1" class="space-y-6">
        <a-upload
          v-model:file-list="createDocumentsForm.file_list"
          draggable
          accept=".doc,.docx,.pdf,.txt,.md,.markdown"
          :limit="10"
          multiple
          :custom-request="handleCustomRequest"
        />

        <div class="flex justify-end">
          <a-button type="primary" @click="nextStep">
            {{ t('admin.datasetDocumentImport.next') }}
          </a-button>
        </div>
      </div>

      <div v-else-if="currentStep === 2" class="text-sm text-slate-500">
        <div class="space-y-6">
          <div class="grid gap-4 md:grid-cols-2">
            <button
              data-test="select-automatic"
              type="button"
              class="rounded-2xl border p-4 text-left transition"
              :class="
                createDocumentsForm.process_type === 'automatic'
                  ? 'border-blue-500 bg-blue-50 text-slate-900'
                  : 'border-slate-200 bg-white text-slate-500'
              "
              @click="createDocumentsForm.process_type = 'automatic'"
            >
              <div class="text-sm font-semibold">
                {{ t('admin.datasetDocumentImport.automaticTitle') }}
              </div>
            </button>

            <button
              data-test="select-custom"
              type="button"
              class="rounded-2xl border p-4 text-left transition"
              :class="
                createDocumentsForm.process_type === 'custom'
                  ? 'border-blue-500 bg-blue-50 text-slate-900'
                  : 'border-slate-200 bg-white text-slate-500'
              "
              @click="createDocumentsForm.process_type = 'custom'"
            >
              <div class="text-sm font-semibold">
                {{ t('admin.datasetDocumentImport.customTitle') }}
              </div>
            </button>
          </div>

          <div v-if="createDocumentsForm.process_type === 'custom'" class="space-y-4 text-slate-700">
            <div class="space-y-2">
              <div class="text-sm font-medium">
                {{ t('admin.datasetDocumentImport.separatorLabel') }}
              </div>
              <div class="grid gap-2">
                <input
                  v-for="(separator, index) in createDocumentsForm.rule.separators"
                  :key="`${index}-${separator}`"
                  :data-test="`separator-${index}`"
                  type="text"
                  class="rounded-lg border border-slate-200 px-3 py-2 text-sm"
                  :value="separator"
                  @input="updateSeparator(index, ($event.target as HTMLInputElement).value)"
                />
              </div>
            </div>

            <div class="grid gap-4 md:grid-cols-2">
              <label class="space-y-2 text-sm">
                <span class="font-medium">
                  {{ t('admin.datasetDocumentImport.chunkSizeLabel') }}
                </span>
                <input
                  v-model.number="createDocumentsForm.rule.chunk_size"
                  data-test="chunk-size"
                  type="number"
                  min="100"
                  max="1000"
                  class="w-full rounded-lg border border-slate-200 px-3 py-2"
                />
              </label>

              <label class="space-y-2 text-sm">
                <span class="font-medium">
                  {{ t('admin.datasetDocumentImport.chunkOverlapLabel') }}
                </span>
                <input
                  v-model.number="createDocumentsForm.rule.chunk_overlap"
                  data-test="chunk-overlap"
                  type="number"
                  min="0"
                  :max="Math.floor(createDocumentsForm.rule.chunk_size * 0.5)"
                  class="w-full rounded-lg border border-slate-200 px-3 py-2"
                />
              </label>
            </div>

            <fieldset class="space-y-2 text-sm">
              <legend class="font-medium">
                {{ t('admin.datasetDocumentImport.preProcessLabel') }}
              </legend>
              <label class="flex items-center gap-2">
                <input
                  v-model="createDocumentsForm.rule.pre_process_rules"
                  type="checkbox"
                  value="remove_extra_space"
                />
                <span>
                  {{ t('admin.datasetDocumentImport.preProcessRules.removeExtraSpace') }}
                </span>
              </label>
              <label class="flex items-center gap-2">
                <input
                  v-model="createDocumentsForm.rule.pre_process_rules"
                  type="checkbox"
                  value="remove_url_and_email"
                />
                <span>
                  {{ t('admin.datasetDocumentImport.preProcessRules.removeUrlAndEmail') }}
                </span>
              </label>
            </fieldset>
          </div>

          <div class="flex items-center justify-between">
            <button
              type="button"
              class="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600"
              @click="previousStep"
            >
              {{ t('admin.datasetDocumentImport.previous') }}
            </button>
            <button
              data-test="submit-create"
              type="button"
              class="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:bg-blue-300"
              :disabled="createDocumentsLoading"
              @click="nextStep"
            >
              {{ t('admin.datasetDocumentImport.submit') }}
            </button>
          </div>
        </div>
      </div>

      <div v-else class="space-y-4">
        <div>
          <h2 class="text-lg font-semibold text-slate-900">
            {{ t('admin.datasetDocumentImport.processingTitle') }}
          </h2>
          <p class="mt-1 text-sm text-slate-500">
            {{ t('admin.datasetDocumentImport.processingHint') }}
          </p>
        </div>

        <div class="space-y-3">
          <div
            v-for="document in documents"
            :key="document.id"
            class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3"
          >
            <div class="text-sm font-medium text-slate-900">{{ document.name }}</div>
            <div class="mt-1 text-sm text-slate-500">{{ getDocumentStatusText(document) }}</div>
          </div>
        </div>

        <router-link
          :to="{ name: 'admin-dataset-documents', params: { dataset_id: datasetId } }"
        >
          <a-button type="primary">{{ t('admin.datasetDocumentImport.confirm') }}</a-button>
        </router-link>
      </div>
    </div>
  </section>
</template>
