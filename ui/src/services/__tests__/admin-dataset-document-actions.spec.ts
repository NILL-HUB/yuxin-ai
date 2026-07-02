import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  deleteAdminDatasetDocument,
  renameAdminDatasetDocument,
  updateAdminDatasetDocumentEnabled,
} from '@/services/admin-dataset-document-actions'

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
}))

vi.mock('@/utils/request', () => ({
  post: mocks.post,
}))

describe('admin dataset document actions service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls rename endpoint with body payload', async () => {
    mocks.post.mockResolvedValue({ message: 'ok' })

    await renameAdminDatasetDocument('dataset-1', 'doc-1', '新名称')

    expect(mocks.post).toHaveBeenCalledWith('/datasets/dataset-1/documents/doc-1/name', {
      body: { name: '新名称' },
    })
  })

  it('calls enabled endpoint with enabled flag', async () => {
    mocks.post.mockResolvedValue({ message: 'ok' })

    await updateAdminDatasetDocumentEnabled('dataset-1', 'doc-1', false)

    expect(mocks.post).toHaveBeenCalledWith('/datasets/dataset-1/documents/doc-1/enabled', {
      body: { enabled: false },
    })
  })

  it('calls delete endpoint', async () => {
    mocks.post.mockResolvedValue({ message: 'ok' })

    await deleteAdminDatasetDocument('dataset-1', 'doc-1')

    expect(mocks.post).toHaveBeenCalledWith('/datasets/dataset-1/documents/doc-1/delete')
  })
})
