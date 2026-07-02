import { type BaseResponse } from '@/models/base'
import { type ToolConfirmation } from '@/models/tool-confirmation'
import { get, post } from '@/utils/request'

export const getToolConfirmations = (status?: string) => {
  const params = status ? { status } : undefined
  return get<BaseResponse<Array<ToolConfirmation>>>(`/tool-confirmations`, { params })
}

export const getToolConfirmation = (id: string) => {
  return get<BaseResponse<ToolConfirmation>>(`/tool-confirmations/${id}`)
}

export const postToolConfirmationConfirm = (id: string) => {
  return post<BaseResponse<ToolConfirmation>>(`/tool-confirmations/${id}/confirm`)
}

export const postToolConfirmationCancel = (id: string) => {
  return post<BaseResponse<ToolConfirmation>>(`/tool-confirmations/${id}/cancel`)
}

export const pollPendingConfirmations = (
  interval: number,
  callback: (confirmations: ToolConfirmation[]) => void,
) => {
  const fetchPending = () => {
    void getToolConfirmations('pending')
      .then((res) => callback(res.data))
      .catch(() => {})
  }
  void fetchPending()
  const timerId = window.setInterval(fetchPending, interval)
  return () => {
    window.clearInterval(timerId)
  }
}
