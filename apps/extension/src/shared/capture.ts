import type { QualityLevel } from './types'

export interface CaptureSource {
  type: 'web'
  url: string
  canonical_url?: string
  title: string
  author?: string
}

export interface SignalLensCapture {
  schema_version: 'signallens.capture.v1'
  capture_id: string
  source: CaptureSource
  document: { format: 'markdown'; text: string; units: [] }
  capture: {
    mode: 'manual'
    producer: 'pagesift-web'
    producer_version: string
    quality: { level: QualityLevel; warnings: string[] }
    extraction_engine: string
  }
}

/** 将 PageSift 提取结果转换为媒介无关的 SignalLens 采集协议。 */
export function buildCapture(input: {
  captureId: string
  title: string
  author?: string
  source: string
  markdown: string
  quality: QualityLevel
  warnings: string[]
  engine: string
}): SignalLensCapture {
  return {
    schema_version: 'signallens.capture.v1',
    capture_id: input.captureId,
    source: {
      type: 'web',
      url: input.source,
      title: input.title,
      ...(input.author ? { author: input.author } : {}),
    },
    document: { format: 'markdown', text: input.markdown, units: [] },
    capture: {
      mode: 'manual',
      producer: 'pagesift-web',
      producer_version: '0.3.1',
      quality: { level: input.quality, warnings: input.warnings },
      extraction_engine: input.engine,
    },
  }
}

