import { ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { generateAdminIconPreview, validateAdminOpenAPISchema } from '@/services/admin-tools'
import { getErrorMessage } from '@/utils/error'

export const useGenerateAdminIconPreview = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const icon = ref<string>('')

  // 2.定义生成图标预览函数
  const handleGenerateIconPreview = async (name: string, description: string) => {
    try {
      loading.value = true
      const resp = await generateAdminIconPreview(name, description)
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

export const useValidateAdminOpenAPISchema = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)

  // 2.定义校验OpenAPI结构处理器
  const handleValidateOpenAPISchema = async (openapi_schema: string) => {
    try {
      loading.value = true
      const resp = await validateAdminOpenAPISchema(openapi_schema)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleValidateOpenAPISchema }
}
