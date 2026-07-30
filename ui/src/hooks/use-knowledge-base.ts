import { ref } from 'vue'
import { Form, Message, Modal } from '@arco-design/web-vue'
import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  deleteKnowledgeDocument,
  generateKnowledgeBaseIconPreview,
  getKnowledgeBase,
  getKnowledgeBasesWithPage,
  getKnowledgeDocument,
  getKnowledgeDocumentsWithPage,
  getKnowledgeSegmentsWithPage,
  hitKnowledgeBase,
  regenerateKnowledgeBaseIcon,
  updateKnowledgeBase,
  updateKnowledgeSegment,
  uploadKnowledgeDocument,
} from '@/services/knowledge-base'
import type {
  GetKnowledgeDocumentsWithPageRequest,
  HitRequest,
  UpdateKnowledgeSegmentRequest,
} from '@/models/knowledge-base'
import { getErrorMessage } from '@/utils/error'

// 获取用户端知识库分页列表
export const useGetKnowledgeBasesWithPage = () => {
  // 1.定义数据，涵盖加载状态、列表以及分页器
  const loading = ref(false)
  const knowledgeBases = ref<Record<string, any>[]>([])
  const defaultPaginator = {
    current_page: 1,
    page_size: 20,
    total_page: 0,
    total_record: 0,
  }
  const paginator = ref(defaultPaginator)

  // 2.定义加载数据函数
  const loadKnowledgeBases = async (init: boolean = false, search_word: string = '') => {
    // 2.1 判断是否初始化，初始化则重置分页器
    if (init) {
      paginator.value = defaultPaginator
    } else if (paginator.value.current_page > paginator.value.total_page) {
      return
    }

    try {
      loading.value = true
      const resp = await getKnowledgeBasesWithPage(
        paginator.value.current_page,
        paginator.value.page_size,
        search_word,
      )
      const data = resp.data

      // 2.2 更新分页器
      paginator.value = data.paginator

      // 2.3 判断是否有更多数据
      if (paginator.value.current_page <= paginator.value.total_page) {
        paginator.value.current_page += 1
      }

      // 2.4 追加或覆盖数据
      if (init) {
        knowledgeBases.value = data.list
      } else {
        knowledgeBases.value.push(...data.list)
      }
    } finally {
      loading.value = false
    }
  }

  return { loading, knowledgeBases, paginator, loadKnowledgeBases }
}

// 删除用户端知识库
export const useDeleteKnowledgeBase = () => {
  const handleDelete = (knowledge_base_id: string, callback?: () => void) => {
    Modal.warning({
      title: '要删除知识库吗?',
      content:
        '删除知识库后，关联该知识库的应用将无法再使用该知识库，所有的提示配置和文档都将被永久删除',
      hideCancel: false,
      onOk: async () => {
        try {
          const resp = await deleteKnowledgeBase(knowledge_base_id)
          Message.success(resp.message)
        } finally {
          callback && callback()
        }
      },
    })
  }

  return { handleDelete }
}

// 新增或更新用户端知识库
export const useCreateOrUpdateKnowledgeBase = () => {
  // 1.定义新增和更新需要使用的数据
  const loading = ref(false)
  const defaultForm = {
    fileList: [] as any,
    icon: '',
    name: '',
    description: '',
  }
  const form = ref(defaultForm)
  const formRef = ref<InstanceType<typeof Form>>()
  const showUpdateModal = ref(false)

  // 2.定义更新模态窗显隐函数
  const updateShowUpdateModal = (new_value: boolean, callback?: () => void) => {
    showUpdateModal.value = new_value
    callback && callback()
  }

  // 3.定义表单提交函数
  const saveKnowledgeBase = async (knowledge_base_id?: string) => {
    try {
      loading.value = true
      if (knowledge_base_id !== undefined && knowledge_base_id !== '') {
        const resp = await updateKnowledgeBase(knowledge_base_id, {
          icon: form.value.icon,
          name: form.value.name,
          description: form.value.description,
        })
        Message.success(resp.message)
      } else {
        const resp = await createKnowledgeBase({
          icon: form.value.icon,
          name: form.value.name,
          description: form.value.description,
        })
        Message.success(resp.message)
      }
    } finally {
      loading.value = false
    }
  }

  return {
    loading,
    form,
    formRef,
    saveKnowledgeBase,
    showUpdateModal,
    updateShowUpdateModal,
  }
}

// 获取用户端知识库详情
export const useGetKnowledgeBase = () => {
  const loading = ref(false)
  const knowledgeBase = ref<Record<string, any>>({})

  const loadKnowledgeBase = async (knowledge_base_id: string) => {
    try {
      loading.value = true
      const resp = await getKnowledgeBase(knowledge_base_id)
      knowledgeBase.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, knowledgeBase, loadKnowledgeBase }
}

// 获取文档分页列表
export const useGetKnowledgeDocumentsWithPage = () => {
  const loading = ref(false)
  const documents = ref<Record<string, any>[]>([])
  const defaultPaginator = {
    current_page: 1,
    page_size: 20,
    total_page: 0,
    total_record: 0,
  }
  const paginator = ref(defaultPaginator)

  const loadDocuments = async (
    knowledge_base_id: string,
    req: GetKnowledgeDocumentsWithPageRequest = {
      current_page: 1,
      page_size: 20,
      search_word: '',
    },
  ) => {
    try {
      loading.value = true
      const resp = await getKnowledgeDocumentsWithPage(knowledge_base_id, req)
      const data = resp.data
      paginator.value = data.paginator
      documents.value = data.list
    } finally {
      loading.value = false
    }
  }

  return { loading, documents, paginator, loadDocuments }
}

// 删除文档
export const useDeleteKnowledgeDocument = () => {
  const handleDelete = (
    knowledge_base_id: string,
    document_id: string,
    callback?: () => void,
  ) => {
    Modal.warning({
      title: '要删除该文档吗?',
      content:
        '删除文档后，知识库/向量数据库将无法检索到该文档，如需暂时关闭该文档的检索，可以选择禁用功能',
      hideCancel: false,
      onOk: async () => {
        try {
          const resp = await deleteKnowledgeDocument(knowledge_base_id, document_id)
          Message.success(resp.message)
          callback && callback()
        } catch (error: unknown) {
          Message.error(getErrorMessage(error, '删除文档失败，请稍后重试'))
          throw error
        }
      },
    })
  }

  return { handleDelete }
}

// 获取文档详情
export const useGetKnowledgeDocument = () => {
  const loading = ref(false)
  const document = ref<Record<string, any>>({})

  const loadDocument = async (knowledge_base_id: string, document_id: string) => {
    try {
      loading.value = true
      const resp = await getKnowledgeDocument(knowledge_base_id, document_id)
      document.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, document, loadDocument }
}

// 获取片段分页列表
export const useGetKnowledgeSegmentsWithPage = () => {
  const loading = ref(false)
  const segments = ref<Record<string, any>[]>([])
  const defaultPaginator = {
    current_page: 1,
    page_size: 20,
    total_page: 0,
    total_record: 0,
  }
  const paginator = ref(defaultPaginator)

  const loadSegments = async (
    knowledge_base_id: string,
    document_id: string,
    init: boolean = false,
    search_word: string = '',
  ) => {
    if (init) {
      paginator.value = defaultPaginator
    } else if (paginator.value.current_page > paginator.value.total_page) {
      return
    }

    try {
      loading.value = true
      const resp = await getKnowledgeSegmentsWithPage(knowledge_base_id, document_id, {
        current_page: paginator.value.current_page,
        page_size: paginator.value.page_size,
        search_word: search_word,
      })
      const data = resp.data
      paginator.value = data.paginator

      if (paginator.value.current_page <= paginator.value.total_page) {
        paginator.value.current_page += 1
      }

      if (init) {
        segments.value = data.list
      } else {
        segments.value.push(...data.list)
      }
    } finally {
      loading.value = false
    }
  }

  return { loading, segments, paginator, loadSegments }
}

// 更新片段内容或启用状态
export const useUpdateKnowledgeSegment = () => {
  const loading = ref(false)

  const handleUpdate = async (
    knowledge_base_id: string,
    document_id: string,
    segment_id: string,
    req: UpdateKnowledgeSegmentRequest,
  ) => {
    try {
      loading.value = true
      const resp = await updateKnowledgeSegment(
        knowledge_base_id,
        document_id,
        segment_id,
        req,
      )
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleUpdate }
}

// 知识库召回测试
export const useHitKnowledgeBase = () => {
  const loading = ref(false)
  const hits = ref<Record<string, any>[]>([])

  const handleHit = async (knowledge_base_id: string, req: HitRequest) => {
    try {
      loading.value = true
      const resp = await hitKnowledgeBase(knowledge_base_id, req)
      hits.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, hits, handleHit }
}

// 重新生成知识库图标
export const useRegenerateKnowledgeBaseIcon = () => {
  const loading = ref(false)
  const icon = ref<string>('')

  const handleRegenerateIcon = async (knowledge_base_id: string) => {
    try {
      loading.value = true
      const resp = await regenerateKnowledgeBaseIcon(knowledge_base_id)
      icon.value = resp.data.icon
      return resp.data.icon
    } catch (error: unknown) {
      let errorMessage = '重新生成图标失败，请稍后重试'
      const normalizedMessage = getErrorMessage(error, '')
      if (normalizedMessage.includes('API_KEY')) {
        errorMessage = '图标生成服务暂时不可用，请联系管理员配置 API Key'
      }
      Message.error(errorMessage)
      throw error
    } finally {
      loading.value = false
    }
  }

  return { loading, icon, handleRegenerateIcon }
}

// 生成知识库图标预览
export const useGenerateKnowledgeBaseIconPreview = () => {
  const loading = ref(false)
  const icon = ref<string>('')

  const handleGenerateIconPreview = async (name: string, description: string) => {
    try {
      loading.value = true
      const resp = await generateKnowledgeBaseIconPreview(name, description)
      icon.value = resp.data.icon
      return resp.data.icon
    } catch (error: unknown) {
      Message.error(getErrorMessage(error, '生成图标失败，请稍后重试或手动上传图标'))
      throw error
    } finally {
      loading.value = false
    }
  }

  return { loading, icon, handleGenerateIconPreview }
}

// 上传文档到知识库（单文件上传，后端自动完成解析与索引）
export const useUploadKnowledgeDocument = () => {
  const loading = ref(false)

  const handleUploadDocument = async (knowledge_base_id: string, file: File) => {
    try {
      loading.value = true
      const resp = await uploadKnowledgeDocument(knowledge_base_id, file)
      Message.success(resp.message)
    } catch (error: unknown) {
      Message.error(getErrorMessage(error, '上传文档失败，请稍后重试'))
      throw error
    } finally {
      loading.value = false
    }
  }

  return { loading, handleUploadDocument }
}

