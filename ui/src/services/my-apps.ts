import { get, ssePost } from '@/utils/request'
import { type MyAppChatRequest, type MyAppListResponse } from '@/models/app-assignment'

export const listMyApps = () => {
  return get<MyAppListResponse['data']>('/my/apps')
}

export const chatWithMyApp = (
  appId: string,
  req: MyAppChatRequest,
  onData: (event_response: Record<string, unknown>) => void,
) => {
  return ssePost(`/my/apps/${appId}/chat`, {
    body: {
      query: req.query,
      image_urls: req.image_urls || [],
      conversation_id: req.conversation_id || '',
      ...(req.confirm_deep_thinking === undefined ? {} : { confirm_deep_thinking: req.confirm_deep_thinking }),
    },
  }, onData)
}
