import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@arco-design/web-vue', () => ({
  Message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  Modal: { warning: vi.fn() },
  Form: {},
}))

vi.mock('@/services/knowledge-base', () => ({
  createKnowledgeBase: vi.fn(),
  updateKnowledgeBase: vi.fn(),
  deleteKnowledgeBase: vi.fn(),
  deleteKnowledgeDocument: vi.fn(),
  generateKnowledgeBaseIconPreview: vi.fn(),
  getKnowledgeBase: vi.fn(),
  getKnowledgeBasesWithPage: vi.fn(),
  getKnowledgeDocument: vi.fn(),
  getKnowledgeDocumentsWithPage: vi.fn(),
  getKnowledgeSegmentsWithPage: vi.fn(),
  hitKnowledgeBase: vi.fn(),
  regenerateKnowledgeBaseIcon: vi.fn(),
  updateKnowledgeSegment: vi.fn(),
  uploadKnowledgeDocument: vi.fn(),
}))

vi.mock('@/services/chunked-upload', () => ({
  uploadFileChunked: vi.fn(),
  SINGLE_UPLOAD_THRESHOLD: 0,
}))

import * as kbService from '@/services/knowledge-base'
import { useCreateOrUpdateKnowledgeBase } from '@/hooks/use-knowledge-base'

const okResponse = { code: 'success', message: 'ok', data: {} } as never

describe('useCreateOrUpdateKnowledgeBase 板块类型与分区模式', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('表单默认使用 mixed / none', () => {
    const { form } = useCreateOrUpdateKnowledgeBase()

    expect(form.value.base_type).toBe('mixed')
    expect(form.value.partition_mode).toBe('none')
  })

  it('创建时提交 base_type 与 partition_mode', async () => {
    vi.mocked(kbService.createKnowledgeBase).mockResolvedValue(okResponse)

    const { form, saveKnowledgeBase } = useCreateOrUpdateKnowledgeBase()
    form.value.name = '素材库'
    form.value.icon = ''
    form.value.description = ''
    form.value.base_type = 'document'
    form.value.partition_mode = 'date_month'

    await saveKnowledgeBase()

    expect(kbService.createKnowledgeBase).toHaveBeenCalledWith(
      expect.objectContaining({ base_type: 'document', partition_mode: 'date_month' }),
    )
  })

  it('编辑已有知识库时不提交 base_type 与 partition_mode', async () => {
    vi.mocked(kbService.updateKnowledgeBase).mockResolvedValue(okResponse)

    const { form, saveKnowledgeBase } = useCreateOrUpdateKnowledgeBase()
    form.value.name = '素材库'
    form.value.icon = ''
    form.value.description = ''
    form.value.base_type = 'video'
    form.value.partition_mode = 'custom'

    await saveKnowledgeBase('kb-1')

    expect(kbService.updateKnowledgeBase).toHaveBeenCalledTimes(1)
    const payload = vi.mocked(kbService.updateKnowledgeBase).mock.calls[0][1] as Record<string, unknown>
    expect(payload).not.toHaveProperty('base_type')
    expect(payload).not.toHaveProperty('partition_mode')
    expect(payload).toEqual(expect.objectContaining({ name: '素材库' }))
  })
})
