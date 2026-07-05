import { ref } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import {
  deleteAllConversationVariables,
  deleteConversationVariable,
  getConversationVariables,
  setConversationVariable,
} from '@/services/conversation-variable'
import type {
  ConversationVariable,
  SetVariableReq,
} from '@/models/conversation-variable'
import { getErrorMessage } from '@/utils/error'
import { i18n } from '@/i18n'

const t = (key: string, params?: Record<string, unknown>) =>
  params ? i18n.global.t(key, params) : i18n.global.t(key)

// 获取会话变量列表
export const useGetConversationVariables = () => {
  const loading = ref(false)
  const variables = ref<ConversationVariable[]>([])

  const loadVariables = async (conversation_id: string) => {
    if (!conversation_id) {
      variables.value = []
      return
    }
    try {
      loading.value = true
      const resp = await getConversationVariables(conversation_id)
      variables.value = resp.data.list || []
    } finally {
      loading.value = false
    }
  }

  return { loading, variables, loadVariables }
}

// 设置会话变量（新增/更新）
export const useSetConversationVariable = () => {
  const loading = ref(false)

  const handleSetVariable = async (
    conversation_id: string,
    req: SetVariableReq,
    isUpdate: boolean = false,
  ) => {
    try {
      loading.value = true
      await setConversationVariable(conversation_id, req)
      Message.success(
        isUpdate
          ? t('appStudio.debug.conversationVariables.updateSuccess')
          : t('appStudio.debug.conversationVariables.addSuccess'),
      )
    } catch (error: unknown) {
      Message.error(getErrorMessage(error, t('common.request.requestFailed')))
      throw error
    } finally {
      loading.value = false
    }
  }

  return { loading, handleSetVariable }
}

// 删除单个变量
export const useDeleteConversationVariable = () => {
  const handleDeleteVariable = async (
    conversation_id: string,
    name: string,
    callback?: () => void,
  ) => {
    Modal.warning({
      title: t('appStudio.debug.conversationVariables.deleteConfirmTitle'),
      content: t('appStudio.debug.conversationVariables.deleteConfirmContent', { name }),
      hideCancel: false,
      onOk: async () => {
        try {
          await deleteConversationVariable(conversation_id, name)
          Message.success(t('appStudio.debug.conversationVariables.deleteSuccess'))
        } catch (error: unknown) {
          Message.error(getErrorMessage(error, t('common.request.requestFailed')))
          throw error
        } finally {
          callback && callback()
        }
      },
    })
  }

  return { handleDeleteVariable }
}

// 清空所有变量
export const useDeleteAllConversationVariables = () => {
  const loading = ref(false)

  const handleDeleteAll = async (
    conversation_id: string,
    callback?: () => void,
  ) => {
    Modal.warning({
      title: t('appStudio.debug.conversationVariables.deleteAllConfirmTitle'),
      content: t('appStudio.debug.conversationVariables.deleteAllConfirmContent'),
      hideCancel: false,
      onOk: async () => {
        try {
          loading.value = true
          await deleteAllConversationVariables(conversation_id)
          Message.success(t('appStudio.debug.conversationVariables.deleteSuccess'))
        } catch (error: unknown) {
          Message.error(getErrorMessage(error, t('common.request.requestFailed')))
          throw error
        } finally {
          loading.value = false
          callback && callback()
        }
      },
    })
  }

  return { loading, handleDeleteAll }
}
