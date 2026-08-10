import { ref } from 'vue'
import { getBuiltinTool, getBuiltinTools, getCategories } from '@/services/builtin-tool'
import type {
  GetBuiltinToolResponse,
  GetBuiltinToolsResponse,
  GetCategoriesResponse,
} from '@/models/builtin-tool'

export const useGetCategories = () => {
  // 1.定义自定义hooks所需数据
  const loading = ref(false)
  const categories = ref<GetCategoriesResponse['data']>([])

  // 2.定义加载数据函数
  const loadCategories = async () => {
    try {
      loading.value = true
      const resp = await getCategories()
      categories.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, categories, loadCategories }
}

export const useGetBuiltinTool = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const builtin_tool = ref<GetBuiltinToolResponse['data']>({} as GetBuiltinToolResponse['data'])

  // 2.定义加载函数
  const loadBuiltinTool = async (provider_name: string, tool_name: string) => {
    try {
      loading.value = true
      const resp = await getBuiltinTool(provider_name, tool_name)
      builtin_tool.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, builtin_tool, loadBuiltinTool }
}

export const useGetBuiltinTools = () => {
  // 1.定义自定义hooks所需数据
  const loading = ref(false)
  const builtin_tools = ref<GetBuiltinToolsResponse['data']>([])

  // 2.定义加载数据函数
  const loadBuiltinTools = async () => {
    try {
      loading.value = true
      const resp = await getBuiltinTools()
      builtin_tools.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, builtin_tools, loadBuiltinTools }
}
