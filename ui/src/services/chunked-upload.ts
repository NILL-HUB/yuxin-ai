import { get, post, upload } from '@/utils/request'
import { type BaseResponse } from '@/models/base'
import storage from '@/utils/storage'

// 分片大小：5MB（与后端默认一致）
const CHUNK_SIZE = 5 * 1024 * 1024
// 小于该值走原有单次上传接口
export const SINGLE_UPLOAD_THRESHOLD = CHUNK_SIZE
// 并发上传分片数
const CONCURRENCY = 3

// 会话缓存键：按指纹保存未完成的 session_id，用于跨调用断点续传
const SESSION_CACHE_PREFIX = 'chunked-upload-session:'

const readCachedSessionId = (fingerprint: string): string => {
  try {
    return storage.get<string>(`${SESSION_CACHE_PREFIX}${fingerprint}`, '')
  } catch {
    return ''
  }
}

const writeCachedSessionId = (fingerprint: string, sessionId: string): void => {
  try {
    storage.set(`${SESSION_CACHE_PREFIX}${fingerprint}`, sessionId)
  } catch {
    /* 隐私模式等场景下写入失败不影响上传 */
  }
}

const clearCachedSessionId = (fingerprint: string): void => {
  try {
    storage.remove(`${SESSION_CACHE_PREFIX}${fingerprint}`)
  } catch {
    /* 忽略 */
  }
}

export interface ChunkedUploadProgress {
  uploadedChunks: number
  totalChunks: number
  percent: number
}

export interface ChunkedUploadResult {
  uploadFileId: string
  name: string
  size: number
  documentId?: string
}

/**
 * 计算秒传指纹：文件大小 + 首/中/尾分片内容的哈希。
 * 全文件哈希在浏览器端对 GB 级文件过慢，故采用抽样指纹。
 * 非安全上下文（如局域网 http）下 crypto.subtle 不可用，此时退化为大小 + 文件名。
 */
const computeFingerprint = async (file: File): Promise<string> => {
  if (!globalThis.crypto?.subtle) {
    return `${file.size}-${file.name}`
  }

  const sampleSize = 256 * 1024
  const offsets = [
    0,
    Math.max(0, Math.floor(file.size / 2) - sampleSize / 2),
    Math.max(0, file.size - sampleSize),
  ]
  const parts: ArrayBuffer[] = []
  for (const offset of offsets) {
    parts.push(await file.slice(offset, offset + sampleSize).arrayBuffer())
  }

  const totalLength = parts.reduce((sum, buf) => sum + buf.byteLength, 0)
  const merged = new Uint8Array(totalLength)
  let cursor = 0
  for (const buf of parts) {
    merged.set(new Uint8Array(buf), cursor)
    cursor += buf.byteLength
  }

  const digest = await crypto.subtle.digest('SHA-256', merged)
  const hex = Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
  return `${file.size}-${hex}`
}

const toResult = (data: Record<string, unknown>): ChunkedUploadResult => {
  return {
    uploadFileId: String(data.upload_file_id ?? ''),
    name: String(data.name ?? ''),
    size: Number(data.size ?? 0),
    documentId: data.document_id ? String(data.document_id) : undefined,
  }
}

/**
 * 上传单个文件（分片上传，含秒传与跨调用断点续传）。
 *
 * 说明：秒传命中时后端会复制既有文件并按 knowledge_base_id 建档，
 * 返回值含 document_id，与正常分片上传 complete 的行为一致。
 * 跨调用续传依赖 localStorage 会话缓存：按文件指纹保存未完成的 session_id，
 * 重试时先查询该会话已收到的分片，命中则只补传缺失分片（后端 init 每次
 * 都会生成新 session_id，故不能靠重新 init 续传）。
 */
export const uploadFileChunked = async (
  knowledgeBaseId: string,
  file: File,
  onProgress?: (progress: ChunkedUploadProgress) => void,
): Promise<ChunkedUploadResult> => {
  const fingerprint = await computeFingerprint(file)
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE)

  // 优先复用上次未完成的会话（跨调用断点续传）
  let sessionId = readCachedSessionId(fingerprint)
  let received = new Set<number>()

  if (sessionId) {
    try {
      const statusResponse = await get<BaseResponse<Record<string, unknown>>>(
        `/space/chunked-uploads/${sessionId}/status`,
      )
      const statusData = statusResponse.data ?? {}
      // 会话仍有效且文件一致时才复用
      if (Number(statusData.total_chunks) === totalChunks) {
        received = new Set((statusData.received_chunks as number[]) ?? [])
      } else {
        sessionId = ''
      }
    } catch {
      // 会话已过期或已 abort，走全新上传
      sessionId = ''
    }
    if (!sessionId) {
      clearCachedSessionId(fingerprint)
    }
  }

  if (!sessionId) {
    const initResponse = await post<BaseResponse<Record<string, unknown>>>(
      '/space/chunked-uploads/init',
      {
        body: {
          filename: file.name,
          total_size: file.size,
          chunk_size: CHUNK_SIZE,
          total_chunks: totalChunks,
          fingerprint,
        },
      },
    )
    const initData = initResponse.data

    // 秒传命中：服务端复制既有文件并建档（无会话，直接返回）
    if (initData.instant) {
      const copied = await post<BaseResponse<Record<string, unknown>>>(
        '/space/chunked-uploads/instant',
        {
          body: {
            upload_file_id: String(initData.upload_file_id ?? ''),
            fingerprint,
            knowledge_base_id: knowledgeBaseId,
          },
        },
      )
      onProgress?.({ uploadedChunks: 1, totalChunks: 1, percent: 100 })
      clearCachedSessionId(fingerprint)
      return toResult(copied.data)
    }

    sessionId = String(initData.session_id ?? '')
    if (!sessionId) {
      throw new Error('初始化分片上传失败')
    }
    writeCachedSessionId(fingerprint, sessionId)
  }

  const pending: number[] = []
  for (let index = 0; index < totalChunks; index += 1) {
    if (!received.has(index)) pending.push(index)
  }

  let uploaded = received.size
  const reportProgress = () => {
    onProgress?.({
      uploadedChunks: uploaded,
      totalChunks,
      percent: Math.floor((uploaded / totalChunks) * 100),
    })
  }
  reportProgress()

  const uploadOne = async (index: number) => {
    const start = index * CHUNK_SIZE
    const blob = file.slice(start, Math.min(start + CHUNK_SIZE, file.size))
    const formData = new FormData()
    formData.append('session_id', sessionId)
    formData.append('index', String(index))
    formData.append('chunk', blob, `${file.name}.part${index}`)

    await upload<BaseResponse<Record<string, unknown>>>('/space/chunked-uploads/chunk', {
      data: formData,
    })
    uploaded += 1
    reportProgress()
  }

  for (let cursor = 0; cursor < pending.length; cursor += CONCURRENCY) {
    const batch = pending.slice(cursor, cursor + CONCURRENCY)
    await Promise.all(batch.map((index) => uploadOne(index)))
  }

  const completed = await post<BaseResponse<Record<string, unknown>>>(
    '/space/chunked-uploads/complete',
    { body: { session_id: sessionId, knowledge_base_id: knowledgeBaseId } },
  )
  clearCachedSessionId(fingerprint)
  return toResult(completed.data)
}
