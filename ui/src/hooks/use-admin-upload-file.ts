import { ref } from 'vue'
import { adminUploadImage } from '@/services/admin-tools'

export const useAdminUploadImage = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const image_url = ref<string>('')

  // 2.定义上传图片处理器
  const handleUploadImage = async (image: File) => {
    try {
      loading.value = true
      const resp = await adminUploadImage(image)
      image_url.value = resp.data.image_url
      return resp
    } finally {
      loading.value = false
    }
  }

  return { loading, image_url, handleUploadImage }
}
