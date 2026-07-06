<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, inject } from 'vue'
import { useRoute } from 'vue-router'
import { useVueFlow } from '@vue-flow/core'
import { cloneDeep, debounce } from 'lodash'
import { getReferencedVariables } from '@/utils/helper'
import { getDatasetsWithPage } from '@/services/dataset'
import { listAdminDatasets } from '@/services/admin-datasets'
import { listSystemKnowledge } from '@/services/admin-system-knowledge'
import { type ValidatedError, Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'

// 旧版 Dataset 数据项
type DatasetItem = {
  id: string
  name: string
  icon: string
  description: string
}

// 新版 KnowledgeBase 数据项（用于节点内展示与回显）
type KnowledgeBaseItem = {
  id: string
  name: string
  description: string
}

// 数据源类型：dataset(旧版) / knowledge_base(新版)
type SourceType = 'dataset' | 'knowledge_base'

type NodeInputField = {
  name: string
  type: string
  value: {
    type: string
    content: {
      ref_node_id: string
      ref_var_name: string
    }
  }
}

type FormInputField = {
  name: string
  type: string
  value: {
    type: string
    content: unknown
  }
  ref: string
  content?: unknown
}

type RetrievalConfig = {
  retrieval_strategy: string
  k: number
  score: number
}

type DatasetRetrievalNodeForm = {
  id: string
  type: string
  title: string
  description: string
  datasets: DatasetItem[]
  // 新版知识库相关字段
  source_type: SourceType
  knowledge_base_ids: string[]
  knowledge_bases: KnowledgeBaseItem[]
  retrieval_config: RetrievalConfig
  inputs: FormInputField[]
  outputs: Array<Record<string, unknown>>
}

// 1.定义自定义组件所需数据
const props = defineProps({
  visible: { type: Boolean, required: true, default: false },
  node: {
    type: Object,
    required: true,
    default: () => {
      return {}
    },
  },
  loading: { type: Boolean, required: true, default: false },
})
const emits = defineEmits(['update:visible', 'updateNode'])
const datasetsModalVisible = ref(false)
const { t } = useI18n()
const form = ref<DatasetRetrievalNodeForm>({
  id: '',
  type: '',
  title: '',
  description: '',
  datasets: [],
  // 默认使用旧版 dataset，向后兼容
  source_type: 'dataset',
  knowledge_base_ids: [],
  knowledge_bases: [],
  retrieval_config: {
    retrieval_strategy: 'semantic',
    k: 4,
    score: 0,
  },
  inputs: [],
  outputs: [],
})
const isSyncingForm = ref(false)

// 注入只读状态
const isReadonly = inject<boolean>('isReadonly', false)
const debounceAutoSave = debounce(() => {
  // 只读模式下不自动保存
  if (isReadonly) return
  void onSubmit({ errors: undefined })
}, 800)
const { nodes, edges } = useVueFlow()

// admin 上下文检测：route.path 以 /admin/ 开头或 route.meta.realm === 'admin'
// admin 上下文下调用 /admin/datasets 跨账号加载所有知识库；space 上下文下调用 /datasets 仅加载当前账号知识库
const route = useRoute()
const isAdminContext = computed(
  () => route.path.startsWith('/admin/') || route.meta.realm === 'admin',
)

// 数据集列表状态（统一 admin/space 双上下文）
const getDatasetsWithPageLoading = ref(false)
const datasets = ref<Record<string, any>[]>([])
const defaultPaginator = {
  current_page: 1,
  page_size: 20,
  total_page: 0,
  total_record: 0,
}
const paginator = ref(defaultPaginator)

/**
 * 统一的数据集加载函数，与原 useGetDatasetsWithPage 的 loadDatasets(init, search_word) 接口保持一致。
 * - admin 上下文：调用 listAdminDatasets → GET /admin/datasets
 * - space 上下文：调用 getDatasetsWithPage → GET /datasets
 */
const loadDatasets = async (init: boolean = false, search_word: string = '') => {
  // 1.初始化时重置分页器；非初始化且已超出总页数则直接返回
  if (init) {
    paginator.value = defaultPaginator
  } else if (paginator.value.current_page > paginator.value.total_page) {
    return
  }

  try {
    getDatasetsWithPageLoading.value = true
    let list: Record<string, any>[] = []
    let respPaginator = defaultPaginator

    if (isAdminContext.value) {
      // admin 上下文：跨账号加载所有知识库
      const data = await listAdminDatasets({
        search_word,
        current_page: paginator.value.current_page,
        page_size: paginator.value.page_size,
      })
      list = data.list || []
      respPaginator = data.paginator
    } else {
      // space 上下文：仅加载当前账号知识库
      const resp = await getDatasetsWithPage(
        paginator.value.current_page,
        paginator.value.page_size,
        search_word,
      )
      list = resp.data.list
      respPaginator = resp.data.paginator
    }

    // 2.更新分页器并预读下一页码
    paginator.value = respPaginator
    if (paginator.value.current_page <= paginator.value.total_page) {
      paginator.value.current_page += 1
    }

    // 3.初始化覆盖，否则追加
    if (init) {
      datasets.value = list
    } else {
      datasets.value.push(...list)
    }
  } finally {
    getDatasetsWithPageLoading.value = false
  }
}

// 新版系统知识库列表状态（系统级知识库全局可见，admin/space 上下文均可调用）
const knowledgeBasesLoading = ref(false)
const knowledgeBases = ref<KnowledgeBaseItem[]>([])

/**
 * 加载系统知识库列表（新版 KnowledgeBase）。
 * 调用 /admin/system-knowledge 接口，仅加载启用状态的知识库。
 * 一次性加载前 100 条，足以覆盖常见的多选场景。
 */
const loadKnowledgeBases = async () => {
  try {
    knowledgeBasesLoading.value = true
    const data = await listSystemKnowledge({
      page: 1,
      page_size: 100,
      search_word: '',
    })
    // 仅保留启用状态的知识库，并映射为节点所需的最小字段集
    knowledgeBases.value = (data.items || [])
      .filter((item) => item.enabled)
      .map((item) => ({
        id: item.id,
        name: item.name,
        description: item.description || '',
      }))
  } catch {
    // 接口不可用时降级为空列表，不阻断节点配置
    knowledgeBases.value = []
  } finally {
    knowledgeBasesLoading.value = false
  }
}

// 系统知识库多选可选项（供 a-select 使用）
const knowledgeBaseOptions = computed(() =>
  knowledgeBases.value.map((kb) => ({
    label: kb.name,
    value: kb.id,
  })),
)

/**
 * 数据源类型切换处理器：切换时清空另一组 id，避免数据残留。
 * - 切到 dataset：清空 knowledge_base_ids / knowledge_bases
 * - 切到 knowledge_base：清空 datasets
 */
const handleSourceTypeChange = (val: SourceType) => {
  if (val === 'dataset') {
    form.value.knowledge_base_ids = []
    form.value.knowledge_bases = []
  } else if (val === 'knowledge_base') {
    form.value.datasets = []
  }
}

/**
 * 新版知识库多选变更处理器：同步维护 knowledge_base_ids 与 knowledge_bases，
 * 保证最多 5 个，并按当前选中顺序回填展示信息。
 */
const handleKnowledgeBaseChange = (ids: (string | number)[]) => {
  // 限制最多 5 个
  const stringIds = ids.map((id) => String(id))
  if (stringIds.length > 5) {
    Message.warning(t('workflowEditor.datasetRetrieval.limitExceeded'))
    // 截断到前 5 个
    form.value.knowledge_base_ids = stringIds.slice(0, 5)
  } else {
    form.value.knowledge_base_ids = stringIds
  }
  // 根据当前选中 id 从已加载列表回填展示信息
  form.value.knowledge_bases = form.value.knowledge_base_ids
    .map((id) => knowledgeBases.value.find((kb) => kb.id === id))
    .filter((kb): kb is KnowledgeBaseItem => !!kb)
}

// 2.定义节点可引用的变量选项
const inputRefOptions = computed(() => {
  return getReferencedVariables(cloneDeep(nodes.value), cloneDeep(edges.value), props.node.id)
})

// 3.定义滚动数据分页处理器
const handleScroll = async (event: UIEvent) => {
  // 3.1 获取滚动距离、可滚动的最大距离、客户端/浏览器窗口的高度
  const { scrollTop, scrollHeight, clientHeight } = event.target as HTMLElement

  // 3.2 判断是否滑动到底部
  if (scrollTop + clientHeight >= scrollHeight - 10) {
    if (getDatasetsWithPageLoading.value) return
    await loadDatasets()
  }
}

// 4.定义取消关联知识库函数
const removeDataset = (idx: number) => {
  form.value.datasets.splice(idx, 1)
}

// 5.知识库选择处理器
const handleSelectDataset = (idx: number) => {
  // 5.1 提取对应的知识库id
  const dataset = datasets.value[idx]

  // 5.2 检测id是否选中，如果是选中则删除
  if (form.value.datasets.some((activateDataset: DatasetItem) => activateDataset.id === dataset.id)) {
    form.value.datasets = form.value.datasets.filter(
      (activateDataset: DatasetItem) => activateDataset.id !== dataset.id,
    )
  } else {
    // 5.3 检测已关联的知识库数量
  if (form.value.datasets.length >= 5) {
      Message.warning(t('workflowEditor.datasetRetrieval.limitExceeded'))
      return
    }
    // 5.4 添加数据到激活知识库列表
    form.value.datasets.push({
      id: dataset.id,
      name: dataset.name,
      icon: dataset.icon,
      description: dataset.description,
    })
  }
}

// 6.定义表单提交函数
const onSubmit = async ({ errors }: { errors: Record<string, ValidatedError> | undefined }) => {
  // 6.1 检查表单是否出现错误，如果出现错误则直接结束
  if (errors) return

  // 6.2 深度拷贝表单数据内容
  const cloneInputs = cloneDeep(form.value.inputs)
  const cloneDatasets = cloneDeep(form.value.datasets)
  const cloneKnowledgeBases = cloneDeep(form.value.knowledge_bases)

  // 6.3 根据 source_type 计算需要提交的 id 列表
  // - dataset：提交 dataset_ids，knowledge_base_ids 置空
  // - knowledge_base：提交 knowledge_base_ids，dataset_ids 置空
  const isKnowledgeBase = form.value.source_type === 'knowledge_base'
  const datasetIds = isKnowledgeBase ? [] : cloneDatasets.map((dataset: DatasetItem) => dataset.id)
  const knowledgeBaseIds = isKnowledgeBase
    ? cloneKnowledgeBases.map((kb: KnowledgeBaseItem) => kb.id)
    : []

  // 6.4 数据校验通过，通过事件触发数据更新
  emits('updateNode', {
    id: props.node.id,
    type: form.value.type,
    title: form.value.title,
    description: form.value.description,
    datasets: cloneDatasets,
    source_type: form.value.source_type,
    dataset_ids: datasetIds,
    knowledge_base_ids: knowledgeBaseIds,
    knowledge_bases: cloneKnowledgeBases,
    meta: {
      datasets: cloneDatasets,
      knowledge_bases: cloneKnowledgeBases,
    },
    retrieval_config: cloneDeep(form.value.retrieval_config),
    inputs: cloneInputs.map((input: FormInputField) => {
      return {
        name: input.name,
        description: '',
        required: true,
        type: input.type === 'ref' ? 'string' : input.type,
        value: {
          type: input.type === 'ref' ? 'ref' : 'literal',
          content:
            input.type === 'ref'
              ? {
                  ref_node_id: input.ref.split('/')[0] || '',
                  ref_var_name: input.ref.split('/')[1] || '',
                }
              : input.content,
        },
        meta: {},
      }
    }),
    outputs: cloneDeep(form.value.outputs),
  })
}

// 7.监听数据，将数据映射到表单模型上
watch(
  () => props.node?.id,
  () => {
    const newNode = props.node
    if (!newNode?.id) return
    isSyncingForm.value = true
    debounceAutoSave.flush()
    debounceAutoSave.cancel()
    const cloneInputs = cloneDeep(newNode.data.inputs)

    // 7.1 回填新版知识库信息：优先取 meta.knowledge_bases（含展示信息），否则用 knowledge_base_ids 占位
    const rawKnowledgeBaseIds: string[] = cloneDeep(newNode.data.knowledge_base_ids) ?? []
    const rawKnowledgeBases: KnowledgeBaseItem[] =
      cloneDeep(newNode.data.meta?.knowledge_bases) ?? []
    // 若 meta 中缺失展示信息但有 id，则用 id 构造占位项，确保回显选中态
    const knowledgeBases: KnowledgeBaseItem[] =
      rawKnowledgeBases.length > 0
        ? rawKnowledgeBases
        : rawKnowledgeBaseIds.map((id) => ({ id, name: id, description: '' }))

    // 7.2 根据 knowledge_base_ids 是否非空自动判定数据源类型（向后兼容：旧节点无该字段则默认 dataset）
    const sourceType: SourceType =
      rawKnowledgeBaseIds.length > 0 ? 'knowledge_base' : 'dataset'

    form.value = {
      id: newNode.id,
      type: newNode.type,
      title: newNode.data.title,
      description: newNode.data.description,
      datasets: cloneDeep(newNode.data.meta?.datasets) ?? [],
      // 新版知识库相关字段
      source_type: sourceType,
      knowledge_base_ids: rawKnowledgeBaseIds,
      knowledge_bases: knowledgeBases,
      retrieval_config: cloneDeep(newNode.data.retrieval_config) ?? {
        k: 4,
        retrieval_strategy: 'semantic',
        score: 0,
      },
      inputs: cloneInputs.map((input: NodeInputField) => {
        // 7.3 计算引用的变量值信息
        const ref =
          input.value.type === 'ref'
            ? `${input.value.content.ref_node_id}/${input.value.content.ref_var_name}`
            : ''

        // 7.4 判断引用的变量值信息是否存在，如果不存在则设置为空
        let refExists = false
        if (input.value.type === 'ref') {
          for (const inputRefOption of inputRefOptions.value) {
            for (const option of inputRefOption.options) {
              if (option.value === ref) {
                refExists = true
                break
              }
            }
          }
        }
        return {
          name: input.name, // 变量名
          type: input.value.type === 'literal' ? input.type : 'ref', // 数据类型(涵盖ref/string/int/float/boolean
          content: input.value.type === 'literal' ? input.value.content : '', // 变量值内容
          ref: input.value.type === 'ref' && refExists ? ref : '', // 变量引用信息，存储引用节点id+引用变量名
        }
      }),
      outputs: [
        { name: 'combine_documents', type: 'string', value: { type: 'generated', content: '' } },
      ],
    }
    nextTick(() => {
      isSyncingForm.value = false
    })
  },
  { immediate: true },
)

watch(
  form,
  () => {
    if (isSyncingForm.value) return
    debounceAutoSave()
  },
  { deep: true },
)

onBeforeUnmount(() => {
  debounceAutoSave.flush()
  debounceAutoSave.cancel()
})

onMounted(() => {
  // 同时加载旧版 dataset 列表与新版系统知识库列表
  loadDatasets(true)
  loadKnowledgeBases()
})
</script>

<template>
  <div
    id="dataset-retrieval-node-info"
    class="absolute top-0 right-0 bottom-0 w-[400px] border-l z-50 bg-white overflow-scroll scrollbar-w-none p-3"
  >    <!-- 只读模式提示横幅 -->
    <div v-if="isReadonly" class="mb-3 p-3 bg-orange-50 border border-orange-200 rounded-lg">
      <div class="flex items-center gap-2 text-orange-700">
        <icon-lock class="flex-shrink-0" />
        <span class="text-sm font-medium">{{ t('workflowEditor.previewMode') }}</span>
      </div>
    </div>


    <!-- 顶部标题信息 -->
    <div class="flex items-center justify-between gap-3 mb-2">
      <!-- 左侧标题 -->
      <div class="flex items-center gap-1 flex-1">
        <a-avatar :size="30" shape="square" class="bg-violet-500 rounded-lg flex-shrink-0">
          <icon-storage />
        </a-avatar>
        <a-input
          v-model:model-value="form.title"
          :disabled="isReadonly"
          :placeholder="t('workflowEditor.titlePlaceholder')"
          class="!bg-white text-gray-700 font-semibold px-2"
        />
      </div>
      <!-- 右侧关闭按钮 -->
      <a-button
        type="text"
        size="mini"
        class="!text-gray700 flex-shrink-0"
        @click="() => emits('update:visible', false)"
      >
        <template #icon>
          <icon-close />
        </template>
      </a-button>
    </div>
    <!-- 描述信息 -->
    <a-textarea
      :auto-size="{ minRows: 3, maxRows: 5 }"
      v-model="form.description"
      :disabled="isReadonly"
      class="rounded-lg text-gray-700 !text-xs"
      :placeholder="t('workflowEditor.descriptionPlaceholder')"
    />
    <!-- 分隔符 -->
    <a-divider class="my-2" />
    <!-- 表单信息 -->
    <a-form size="mini" :model="form" :disabled="isReadonly" layout="vertical">
      <!-- 输入参数 -->
      <div class="flex flex-col gap-2">
        <!-- 标题&操作按钮 -->
        <div class="flex items-center justify-between">
          <!-- 左侧标题 -->
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div class="">{{ t('workflowEditor.inputParameters') }}</div>
            <a-tooltip :content="t('workflowEditor.modelConfig.help')">
              <icon-question-circle />
            </a-tooltip>
          </div>
        </div>
        <!-- 字段名 -->
        <div class="flex items-center gap-1 text-xs text-gray-500 mb-2">
          <div class="w-[20%]">{{ t('workflowEditor.parameterName') }}</div>
          <div class="w-[25%]">{{ t('workflowEditor.parameterType') }}</div>
          <div class="w-[55%]">{{ t('workflowEditor.parameterValue') }}</div>
        </div>
        <!-- 循环遍历字段列表 -->
        <div v-for="(input, idx) in form?.inputs" :key="idx" class="flex items-center gap-1">
          <div class="w-[20%] flex-shrink-0">
            <div class="text-xs text-gray-500">{{ input.name }}</div>
          </div>
          <div class="w-[25%] flex-shrink-0">
            <a-select
              size="mini"
              v-model="input.type"
              class="px-2"
              :options="[
                { label: t('workflowEditor.variableTypes.ref'), value: 'ref' },
                { label: t('workflowEditor.variableTypes.string'), value: 'string' },
                { label: t('workflowEditor.variableTypes.int'), value: 'int' },
                { label: t('workflowEditor.variableTypes.float'), value: 'float' },
                { label: t('workflowEditor.variableTypes.boolean'), value: 'boolean' },
              ]"
            />
          </div>
          <div class="w-[55%] flex-shrink-0 flex items-center gap-1">
            <a-input
              v-if="input.type !== 'ref'"
              size="mini"
              v-model="input.content"
              :placeholder="t('workflowEditor.parameterValue')"
            />
            <a-select
              v-else
              :placeholder="t('workflowEditor.selectReference')"
              size="mini"
              tag-nowrap
              v-model="input.ref"
              :options="inputRefOptions"
            />
          </div>
        </div>
      </div>
      <a-divider class="my-4" />
      <!-- 检索策略 -->
      <div class="flex flex-col gap-2">
        <!-- 标题&操作按钮 -->
        <div class="flex items-center justify-between">
          <!-- 左侧标题 -->
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div class="">{{ t('workflowEditor.datasetRetrieval.title') }}</div>
            <a-tooltip :content="t('workflowEditor.datasetRetrieval.help')">
              <icon-question-circle />
            </a-tooltip>
          </div>
        </div>
        <a-radio-group
          v-model="form.retrieval_config.retrieval_strategy"
          default-value="semantic"
          :options="[
            { label: t('workflowEditor.datasetRetrieval.strategyHybrid'), value: 'hybrid' },
            { label: t('workflowEditor.datasetRetrieval.strategyFullText'), value: 'full_text' },
            { label: t('workflowEditor.datasetRetrieval.strategySemantic'), value: 'semantic' },
          ]"
        />
      </div>
      <a-divider class="my-4" />
      <!-- 最大召回数量 -->
      <div class="flex flex-col gap-2">
        <!-- 标题&操作按钮 -->
        <div class="flex items-center justify-between">
          <!-- 左侧标题 -->
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div class="">{{ t('workflowEditor.datasetRetrieval.maxRecallTitle') }}</div>
            <a-tooltip :content="t('workflowEditor.datasetRetrieval.maxRecallHelp')">
              <icon-question-circle />
            </a-tooltip>
          </div>
        </div>
        <div class="flex items-center gap-4 w-full pl-3">
          <a-slider v-model="form.retrieval_config.k" :step="1" :min="1" :max="10" />
          <a-input-number
            size="mini"
            v-model="form.retrieval_config.k"
            class="w-[80px]"
            :default-value="4"
          />
        </div>
      </div>
      <a-divider class="my-4" />
      <!-- 最小匹配度 -->
      <div class="flex flex-col gap-2">
        <!-- 标题&操作按钮 -->
        <div class="flex items-center justify-between">
          <!-- 左侧标题 -->
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div class="">{{ t('workflowEditor.datasetRetrieval.minScoreTitle') }}</div>
            <a-tooltip :content="t('workflowEditor.datasetRetrieval.minScoreHelp')">
              <icon-question-circle />
            </a-tooltip>
          </div>
        </div>
        <div class="flex items-center gap-4 w-full pl-3">
          <a-slider v-model="form.retrieval_config.score" :step="0.01" :min="0" :max="0.99" />
          <a-input-number
            size="mini"
            v-model="form.retrieval_config.score"
            class="w-[80px]"
            :min="0"
            :max="0.99"
            :step="0.01"
            :precision="2"
            :default-value="0.5"
          />
        </div>
      </div>
      <a-divider class="my-4" />
      <!-- 数据源类型切换 -->
      <div class="flex flex-col gap-2">
        <!-- 标题 -->
        <div class="flex items-center gap-2 text-gray-700 font-semibold">
          <div class="">{{ t('workflowEditor.datasetRetrieval.sourceType') }}</div>
        </div>
        <!-- 类型切换 radio -->
        <a-radio-group
          v-model="form.source_type"
          @change="(val: string | number | boolean) => handleSourceTypeChange(val as SourceType)"
          :options="[
            { label: t('workflowEditor.datasetRetrieval.sourceTypes.dataset'), value: 'dataset' },
            { label: t('workflowEditor.datasetRetrieval.sourceTypes.knowledgeBase'), value: 'knowledge_base' },
          ]"
        />
      </div>
      <a-divider class="my-4" />
      <!-- 关联知识库（旧版 dataset） -->
      <div v-if="form.source_type === 'dataset'" class="flex flex-col gap-2">
        <!-- 标题&操作按钮 -->
        <div class="flex items-center justify-between">
          <!-- 左侧标题 -->
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div class="">{{ t('workflowEditor.datasetRetrieval.bindDataset') }}</div>
            <a-tooltip :content="t('workflowEditor.datasetRetrieval.bindDatasetHelp')">
              <icon-question-circle />
            </a-tooltip>
          </div>
          <!-- 右侧关联知识库按钮 -->
          <a-button
            size="mini"
            type="text"
            class="!text-gray-700"
            @click="() => (datasetsModalVisible = true)"
          >
            <template #icon>
              <icon-plus />
            </template>
          </a-button>
        </div>
        <div v-if="form.datasets?.length > 0" class="flex flex-col gap-1">
          <div
            v-for="(dataset, idx) in form.datasets"
            :key="dataset.id"
            class="flex items-center justify-between bg-white p-3 rounded-lg cursor-pointer hover:shadow-sm group border"
          >
            <!-- 左侧知识库信息 -->
            <div class="flex items-center gap-2">
              <!-- 图标 -->
              <a-avatar
                :size="36"
                shape="square"
                class="rounded flex-shrink-0"
                :image-url="dataset.icon"
              />
              <!-- 名称与描述信息 -->
              <div class="flex flex-col flex-1 gap-1 h-9">
                <div class="text-gray-700 font-bold leading-[18px] line-clamp-1 break-all">
                  {{ dataset.name }}
                </div>
                <div class="text-gray-500 text-xs line-clamp-1 break-all">
                  {{ dataset.description }}
                </div>
              </div>
            </div>
            <!-- 右侧删除按钮 -->
            <a-button
              v-if="!isReadonly"
              size="mini"
              type="text"
              class="hidden group-hover:block flex-shrink-0 ml-2 !text-red-700 rounded"
              @click="() => removeDataset(idx)"
            >
              <template #icon>
                <icon-delete />
              </template>
            </a-button>
          </div>
        </div>
        <div v-else class="text-xs text-gray-500 leading-[22px]">
          {{ t('workflowEditor.datasetRetrieval.emptyTip') }}
        </div>
      </div>
      <!-- 选择知识库（新版 knowledge_base） -->
      <div v-else class="flex flex-col gap-2">
        <!-- 标题 -->
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div class="">{{ t('workflowEditor.datasetRetrieval.knowledgeBaseLabel') }}</div>
          </div>
          <div class="text-xs text-gray-500">{{ t('workflowEditor.datasetRetrieval.knowledgeBaseMaxHint') }}</div>
        </div>
        <!-- 多选选择器 -->
        <a-select
          multiple
          allow-search
          :loading="knowledgeBasesLoading"
          :model-value="form.knowledge_base_ids"
          :options="knowledgeBaseOptions"
          :placeholder="t('workflowEditor.datasetRetrieval.knowledgeBasePlaceholder')"
          :disabled="isReadonly"
          @change="handleKnowledgeBaseChange"
        />
        <!-- 已选知识库列表（展示名称与描述） -->
        <div v-if="form.knowledge_bases?.length > 0" class="flex flex-col gap-1">
          <div
            v-for="kb in form.knowledge_bases"
            :key="kb.id"
            class="flex items-center justify-between bg-white p-3 rounded-lg border"
          >
            <div class="flex flex-col flex-1 gap-1 min-w-0">
              <div class="text-gray-700 font-bold leading-[18px] line-clamp-1 break-all">
                {{ kb.name }}
              </div>
              <div class="text-gray-500 text-xs line-clamp-1 break-all">
                {{ kb.description || '-' }}
              </div>
            </div>
          </div>
        </div>
      </div>
      <a-divider class="my-4" />
      <!-- 输出参数 -->
      <div class="flex flex-col gap-2">
        <!-- 输出标题 -->
        <div class="font-semibold text-gray-700">{{ t('workflowEditor.outputData') }}</div>
        <!-- 字段标题 -->
        <div class="text-gray-500 text-xs">{{ t('workflowEditor.parameterName') }}</div>
        <!-- 输出参数列表 -->
        <div v-for="(output, idx) in form?.outputs" :key="idx" class="flex flex-col gap-2">
          <div class="flex items-center gap-2">
            <div class="text-gray-700">{{ output.name }}</div>
            <div class="text-gray-500 bg-gray-200 px-1 py-0.5 rounded">{{ output.type }}</div>
          </div>
        </div>
      </div>
    </a-form>
    <!-- 关联知识库 -->
    <a-modal
      :visible="datasetsModalVisible"
      hide-title
      :footer="false"
      :width="400"
      modal-class="h-[calc(100vh-32px)]"
      @cancel="() => (datasetsModalVisible = false)"
    >
      <!-- 顶部标题 -->
      <div class="flex items-center justify-between mb-6">
        <div class="text-lg font-bold text-gray-700">{{ t('workflowEditor.datasetRetrieval.chooseDatasetTitle') }}</div>
        <a-button
          type="text"
          class="!text-gray-700"
          size="small"
          @click="() => (datasetsModalVisible = false)"
        >
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>
      <!-- 中间知识库容器 -->
      <div class="h-[calc(100vh-180px)] mb-4 overflow-scroll scrollbar-w-none">
        <a-spin
          :loading="getDatasetsWithPageLoading"
          class="block h-full w-full scrollbar-w-none overflow-scroll"
          @scroll="handleScroll"
        >
          <!-- 知识库列表 -->
          <div class="flex flex-col gap-2">
            <!-- 有数据UI状态 -->
            <div
              v-for="(dataset, idx) in datasets"
              :key="dataset.id"
              :class="`flex items-center gap-2 border px-3 py-2 rounded-lg cursor-pointer hover:bg-blue-50 hover:border-blue-700 ${form.datasets.some((activateDataset: DatasetItem) => activateDataset.id === dataset.id) ? 'bg-blue-50 border-blue-700' : ''}`"
              @click="() => handleSelectDataset(idx)"
            >
              <a-avatar
                :size="24"
                shape="square"
                class="flex-shrink-0 rounded"
                :image-url="dataset.icon"
              />
              <div class="line-clamp-1 text-gray-500 flex-1">{{ dataset.name }}</div>
            </div>
            <!-- 无数据UI状态 -->
            <a-empty
              v-if="datasets.length === 0"
              :description="t('workflowEditor.datasetRetrieval.noAvailable')"
              class="h-[400px] flex flex-col items-center justify-center"
            />
          </div>
          <!-- 加载器 -->
          <a-row v-if="paginator.total_page >= 2">
            <!-- 加载数据中 -->
            <a-col
              v-if="getDatasetsWithPageLoading"
              :span="24"
              class="!text-center"
            >
              <a-space class="my-4">
                <a-spin />
                <div class="text-gray-400">{{ t('workflowEditor.datasetRetrieval.loading') }}</div>
              </a-space>
            </a-col>
            <!-- 数据加载完成 -->
            <a-col v-else-if="paginator.current_page > paginator.total_page" :span="24" class="!text-center">
              <div class="text-gray-400 my-4">{{ t('workflowEditor.datasetRetrieval.loaded') }}</div>
            </a-col>
          </a-row>
        </a-spin>
      </div>
      <!-- 底部选中知识库及按钮 -->
      <div class="flex items-center justify-between">
        <!-- 左侧提示文字 -->
        <div class="">{{ t('workflowEditor.datasetRetrieval.selectedCount', { count: form.datasets.length }) }}</div>
        <!-- 按钮组 -->
        <a-space :size="12">
          <a-button type="primary" class="rounded-lg" @click="() => (datasetsModalVisible = false)">
            {{ t('workflowEditor.datasetRetrieval.chooseDatasetButton') }}
          </a-button>
        </a-space>
      </div>
    </a-modal>
  </div>
</template>
