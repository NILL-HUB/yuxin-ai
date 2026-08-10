import { ref } from 'vue'
import { getAdminAppAnalysis } from '@/services/admin-apps'
import type { GetAppAnalysisResponse } from '@/models/analysis'

export const useGetAdminAppAnalysis = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const app_analysis = ref<GetAppAnalysisResponse['data']>({} as GetAppAnalysisResponse['data'])

  // 2.定义加载数据处理器
  const loadAppAnalysis = async (appId: string) => {
    try {
      loading.value = true
      const resp = await getAdminAppAnalysis(appId)
      app_analysis.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, app_analysis, loadAppAnalysis }
}
