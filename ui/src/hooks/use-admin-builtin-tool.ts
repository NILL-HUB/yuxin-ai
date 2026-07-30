import { ref } from 'vue'
import { getAdminBuiltinCategories, getAdminBuiltinTools } from '@/services/admin-tools'

export const useGetAdminCategories = () => {
  // 1.定义自定义hooks所需数据
  const loading = ref(false)
  const categories = ref<Record<string, any>>([])

  // 2.定义加载数据函数
  const loadCategories = async () => {
    try {
      loading.value = true
      const resp = await getAdminBuiltinCategories()
      categories.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, categories, loadCategories }
}

export const useGetAdminBuiltinTools = () => {
  // 1.定义自定义hooks所需数据
  const loading = ref(false)
  const builtin_tools = ref<Record<string, any>>([])

  // 2.定义加载数据函数
  const loadBuiltinTools = async () => {
    try {
      loading.value = true
      const resp = await getAdminBuiltinTools()
      builtin_tools.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, builtin_tools, loadBuiltinTools }
}
