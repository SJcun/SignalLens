export interface HealthResponse {
  status: 'ok'
  service: 'signallens-api'
}

export type AnalysisStatus = 'pending' | 'running' | 'completed' | 'failed'
export type Recommendation = 'ignore' | 'summary_enough' | 'selective_read' | 'deep_read'

export interface TriageResult {
  relevance: 'low' | 'medium' | 'high' | 'very_high'
  intrinsic_signal: 'low' | 'medium' | 'high'
  novelty_signal: 'low' | 'medium' | 'high' | 'unknown'
  exploration_value: 'low' | 'medium' | 'high'
  discovery_type: 'profile_match' | 'adjacent' | 'outside_profile_high_value'
  decision: 'ignore' | 'continue'
  reason: string
  why_outside_profile: string | null
}

export interface ContentAnalysisResult {
  one_sentence_summary: string
  summary: string
  key_points: string[]
  counterarguments: string[]
  limitations: string[]
  unresolved_questions: string[]
  unverified_claims: string[]
}

export interface ReadingPlanItem {
  section: string
  action: 'skip' | 'skim' | 'read' | 'deep_read'
  reason: string
}

export interface PersonalEvaluationResult {
  relevance: 'low' | 'medium' | 'high' | 'very_high'
  knowledge_overlap: 'low' | 'medium' | 'high'
  known_or_redundant: boolean
  novel_information: string[]
  exploration_value: 'low' | 'medium' | 'high'
  perspective_diversity: 'low' | 'medium' | 'high'
  discovery_type: 'profile_match' | 'adjacent' | 'outside_profile_high_value'
  recommendation: Recommendation
  recommendation_reason: string
  why_outside_profile: string | null
  reading_plan: ReadingPlanItem[]
}

export interface ContentSummary {
  id: string
  title: string
  author: string | null
  source_url: string
  source_type: string
  capture_quality: string
  created_at: string
  analysis_id: string
  analysis_status: AnalysisStatus
  one_sentence_summary: string | null
  recommendation: string | null
  discovery_type: string | null
}

export interface ContentDetail extends ContentSummary {
  markdown: string
  triage: TriageResult | null
  content_analysis: ContentAnalysisResult | null
  personal_evaluation: PersonalEvaluationResult | null
}

/** 统一处理非成功响应，保留后端给出的可读错误。 */
async function apiResponse<T>(response: Response): Promise<T> {
  if (response.ok) return response.json() as Promise<T>
  const body = await response.json().catch(() => null) as { detail?: string } | null
  throw new Error(body?.detail || `API 请求失败（${response.status}）`)
}

/** 请求后端健康状态，确认 Web 与新服务之间的连接。 */
export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch('/api/v1/health')
  return apiResponse<HealthResponse>(response)
}

/** 获取最近采集的内容及最新分析状态。 */
export async function getContents(): Promise<ContentSummary[]> {
  const response = await fetch('/api/v1/contents')
  return apiResponse<ContentSummary[]>(response)
}

/** 获取单篇内容的原始 Markdown 与完整分析结果。 */
export async function getContent(contentId: string): Promise<ContentDetail> {
  const response = await fetch(`/api/v1/contents/${encodeURIComponent(contentId)}`)
  return apiResponse<ContentDetail>(response)
}
