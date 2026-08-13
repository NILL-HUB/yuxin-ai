import { type BaseResponse } from '@/models/base'
import { type ToolConfirmation } from '@/models/tool-confirmation'
import { get, post } from '@/utils/request'
import { getOrCreateVisitorId } from '@/utils/visitor'

export const getToolConfirmations = (status?: string) => {
  const params = status ? { status } : undefined
  return get<BaseResponse<Array<ToolConfirmation>>>(`/tool-confirmations`, { params })
}

export const getToolConfirmation = (id: string) => {
  return get<BaseResponse<ToolConfirmation>>(`/tool-confirmations/${id}`)
}

const withVisitorParam = (url: string, visitorId?: string) => {
  const id = visitorId ?? getOrCreateVisitorId()
  if (!id) return url
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}visitor_id=${encodeURIComponent(id)}`
}

export const postToolConfirmationConfirm = (id: string, visitorId?: string) => {
  return post<BaseResponse<ToolConfirmation>>(withVisitorParam(`/tool-confirmations/${id}/confirm`, visitorId))
}

export const postToolConfirmationCancel = (id: string, visitorId?: string) => {
  return post<BaseResponse<ToolConfirmation>>(withVisitorParam(`/tool-confirmations/${id}/cancel`, visitorId))
}

export const postToolConfirmationRedirect = (id: string, message: string, visitorId?: string) => {
  return post<BaseResponse<{ redirected: boolean }>>(
    withVisitorParam(`/tool-confirmations/${id}/redirect`, visitorId),
    { body: { message } },
  )
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
