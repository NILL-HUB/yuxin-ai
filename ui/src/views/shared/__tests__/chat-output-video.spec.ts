import { describe, expect, it } from 'vitest'

import {
  buildChatOutputParts,
  extractArtifactFromToolObservation,
  isVideoArtifact,
  normalizeChatOutputParts,
  type ChatOutputPart,
} from '../chat-output'

/**
 * 成片（视频）产物必须走独立 part 类型。
 *
 * 为什么锁定：若视频落进 artifact 分支，前端只渲染「下载附件」链接，
 * 用户在对话里看不到成片——这正是本次要补的能力，故用断言防回退。
 */

const videoArtifact = () => ({
  name: '成片',
  url: 'https://cdn.example.com/artifacts/out.mp4',
  mime_type: 'video/mp4',
  extension: 'mp4',
})

describe('isVideoArtifact', () => {
  it('detects video by mime type', () => {
    expect(isVideoArtifact({ name: 'a', url: 'https://x/a', mime_type: 'video/mp4' })).toBe(true)
  })

  it('detects video by extension without dot', () => {
    expect(isVideoArtifact({ name: 'a', url: 'https://x/a', extension: 'mp4' })).toBe(true)
  })

  it('detects video by url suffix when metadata is missing', () => {
    expect(isVideoArtifact({ name: 'a', url: 'https://cdn.example.com/a.mp4' })).toBe(true)
  })

  it('does not misclassify images as video', () => {
    expect(isVideoArtifact({ name: 'a', url: 'https://cdn.example.com/a.png', mime_type: 'image/png' })).toBe(false)
  })

  it('does not misclassify plain files as video', () => {
    expect(isVideoArtifact({ name: 'a', url: 'https://cdn.example.com/a.pdf' })).toBe(false)
  })
})

describe('buildChatOutputParts', () => {
  it('emits a video part instead of a download-only artifact part', () => {
    const parts = buildChatOutputParts('已生成成片', [videoArtifact()])

    const videoPart = parts.find(part => part.type === 'video') as Extract<ChatOutputPart, { type: 'video' }> | undefined
    expect(videoPart).toBeDefined()
    expect(videoPart?.url).toBe('https://cdn.example.com/artifacts/out.mp4')
    expect(videoPart?.name).toBe('成片')
    // 不得同时产出 artifact part（否则会多一个多余的「下载附件」卡片）
    expect(parts.some(part => part.type === 'artifact')).toBe(false)
  })

  it('keeps non-video files on the artifact branch', () => {
    const parts = buildChatOutputParts('', [
      { name: '报告', url: 'https://cdn.example.com/report.pdf', mime_type: 'application/pdf' },
    ])

    expect(parts.some(part => part.type === 'artifact')).toBe(true)
    expect(parts.some(part => part.type === 'video')).toBe(false)
  })

  it('keeps images on the image branch', () => {
    const parts = buildChatOutputParts('', [
      { name: '图', url: 'https://cdn.example.com/a.png', mime_type: 'image/png' },
      videoArtifact(),
    ])

    expect(parts.some(part => part.type === 'image')).toBe(true)
    expect(parts.some(part => part.type === 'video')).toBe(true)
  })
})

describe('normalizeChatOutputParts', () => {
  it('round-trips a video part from the backend payload', () => {
    const parts = normalizeChatOutputParts(
      [{ type: 'video', url: 'https://cdn.example.com/out.mp4', name: '成片', mime_type: 'video/mp4' }],
      '',
      [],
    )

    expect(parts).toHaveLength(1)
    expect(parts[0].type).toBe('video')
  })

  it('rebuilds a video part from artifacts when parts are empty', () => {
    const parts = normalizeChatOutputParts([], '来了', [videoArtifact()] as never)

    expect(parts.some(part => part.type === 'video')).toBe(true)
  })
})

describe('extractArtifactFromToolObservation', () => {
  it('extracts the artifact from a successful tool payload', () => {
    const observation = JSON.stringify({
      ok: true,
      mode: 'local',
      artifact: videoArtifact(),
    })

    const artifact = extractArtifactFromToolObservation(observation)

    expect(artifact?.url).toBe('https://cdn.example.com/artifacts/out.mp4')
  })

  it('returns null when the tool payload has no artifact', () => {
    expect(extractArtifactFromToolObservation(JSON.stringify({ ok: true, task_id: 't1' }))).toBeNull()
  })

  it('returns null for failed tool payloads', () => {
    expect(extractArtifactFromToolObservation(JSON.stringify({ ok: false, artifact: videoArtifact() }))).toBeNull()
  })

  it('returns null for plain text observations', () => {
    expect(extractArtifactFromToolObservation('视频已生成 https://cdn.example.com/a.mp4')).toBeNull()
  })

  it('returns null for malformed json', () => {
    expect(extractArtifactFromToolObservation('{ ok: true')).toBeNull()
  })
})
