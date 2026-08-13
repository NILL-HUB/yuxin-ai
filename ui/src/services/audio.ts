import { ssePost, upload } from '@/utils/request'
import type { BaseResponse } from '@/models/base'

export interface AudioToTextOptions {
    language?: string
    provider?: string
    model?: string
}

// 语音转文本输入接口
export const audioToText = (file: Blob, options: AudioToTextOptions = {}) => {
    // 1.构建表单并添加图片数据
    const formData = new FormData()
    formData.append('file', file, 'recording.wav')
    if (options.language) formData.append('language', options.language)
    if (options.provider) formData.append('provider', options.provider)
    if (options.model) formData.append('model', options.model)

    // 2.调用upload服务实现图片上传
    return upload<BaseResponse<{ text: string }>>(`/audio/audio-to-text`, {
        data: formData,
    })
}

// 消息转语音服务接口
export const messageToAudio = (
    message_id: string,
    onData: (event_response: Record<string, unknown>) => void,
) => {
    return ssePost(`/audio/message-to-audio`, { body: { message_id } }, onData)
}

// 指定文本转语音服务接口（复用消息上下文音色）
export const textToAudio = (
    message_id: string,
    text: string,
    onData: (event_response: Record<string, unknown>) => void,
    sentenceStream: boolean = false,
) => {
    return ssePost(
        `/audio/text-to-audio`,
        { body: { message_id, text, sentence_stream: sentenceStream } },
        onData,
    )
}
