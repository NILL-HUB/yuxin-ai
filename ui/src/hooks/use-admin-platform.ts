import { ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { getAdminAppWechatConfig, updateAdminAppWechatConfig } from '@/services/admin-apps'
import type { GetWechatConfigResponse, UpdateWechatConfigRequest } from '@/models/platform'

export const useGetAdminWechatConfig = () => {
  // 1.定义自定义hooks所需数据
  const loading = ref(false)
  const wechat_config = ref<GetWechatConfigResponse['data']>({} as GetWechatConfigResponse['data'])

  // 2.定义加载数据处理器
  const loadWechatConfig = async (appId: string) => {
    try {
      loading.value = true
      const resp = await getAdminAppWechatConfig(appId)
      wechat_config.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, wechat_config, loadWechatConfig }
}

export const useUpdateAdminWechatConfig = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)

  // 2.定义更新微信配置处理器
  const handleUpdateWechatConfig = async (appId: string, req: UpdateWechatConfigRequest) => {
    try {
      loading.value = true
      const resp = await updateAdminAppWechatConfig(appId, req)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleUpdateWechatConfig }
}
