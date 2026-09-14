import { get, post, upload } from '@/utils/request'
import { type BaseResponse } from '@/models/base'

// 分片大小：5MB（与后端默认一致）
const CHUNK_SIZE = 5 * 1024 * 1024
// 小于该值走原有单次上传接口
export const SINGLE_UPLOAD_THRESHOLD = CHUNK_SIZE
// 并发上传分片数
const CONCURRENCY = 3

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
 * 上传单个文件（分片上传，含秒传与断点续传）。
 *
 * 说明：秒传接口当前只复制既有文件、不建档（后端 instant_upload 未接 knowledge_base_id），
 * 因此秒传命中时不会在知识库产生新文档；完整建档仍需后端补齐后由 complete 完成。
 */
export const uploadFileChunked = async (
  knowledgeBaseId: string,
  file: File,
  onProgress?: (progress: ChunkedUploadProgress) => void,
): Promise<ChunkedUploadResult> => {
  const fingerprint = await computeFingerprint(file)
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE)

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

  // 秒传命中：服务端复制既有文件（当前不建档）
  if (initData.instant) {
    const copied = await post<BaseResponse<Record<string, unknown>>>(
      '/space/chunked-uploads/instant',
      { body: { upload_file_id: String(initData.upload_file_id ?? ''), fingerprint } },
    )
    onProgress?.({ uploadedChunks: 1, totalChunks: 1, percent: 100 })
    return toResult(copied.data)
  }

  const sessionId = String(initData.session_id ?? '')

  // 断点续传：查询服务端已收到的分片
  let received = new Set<number>()
  try {
    const statusResponse = await get<BaseResponse<Record<string, unknown>>>(
      `/space/chunked-uploads/${sessionId}/status`,
    )
    received = new Set((statusResponse.data.received_chunks as number[]) ?? [])
  } catch {
    received = new Set<number>()
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
  return toResult(completed.data)
}
