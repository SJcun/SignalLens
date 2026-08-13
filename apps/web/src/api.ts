import { authenticatedFetch, clearAccessToken } from './auth'

export interface HealthResponse {
  status: 'ok'
  service: 'signallens-api'
}

export interface LoginResult {
  access_token: string
  token_type: 'bearer'
  username: string
  must_change_password: boolean
  expires_at: string
}

export interface CurrentUser {
  username: string
  must_change_password: boolean
}

export interface PluginKeyStatus {
  configured: boolean
  key_prefix: string | null
  created_at: string | null
  last_used_at: string | null
}

export interface GeneratedPluginKey {
  api_key: string
  key_prefix: string
  created_at: string
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

export interface KnownTopic {
  topic: string
  level: 'basic' | 'intermediate' | 'advanced'
}

export interface UserProfile {
  focus_topics: string[]
  known_topics: KnownTopic[]
  reading_goals: string[]
  preferred_depth: 'quick' | 'balanced' | 'deep'
  time_budget_minutes: number
  exploration_level: 'low' | 'medium' | 'high'
  evaluation_mode: boolean
  questionnaire_completed: boolean
  updated_at: string
}

export type ProfileUpdate = Omit<UserProfile, 'questionnaire_completed' | 'updated_at'>

export interface ArticleFeedback {
  id: string
  analysis_id: string
  preferred_recommendation: Recommendation | null
  recommendation_accuracy: 'too_high' | 'accurate' | 'too_low'
  time_worthwhile: 'no' | 'partly' | 'yes'
  new_knowledge: 'none' | 'some' | 'much'
  summary_quality: 'accurate' | 'omission' | 'misleading' | 'not_sure'
  key_takeaway: string | null
  ai_recommendation: string | null
  model: string | null
  prompt_version: string
  updated_at: string
}

export type FeedbackUpdate = Pick<
  ArticleFeedback,
  'time_worthwhile' | 'new_knowledge' | 'summary_quality' | 'key_takeaway'
> & { preferred_recommendation: Recommendation }

export interface CalibrationStats {
  evaluation_mode: boolean
  questionnaire_completed: boolean
  completed_analyses: number
  feedback_count: number
  accurate_count: number
  too_high_count: number
  too_low_count: number
  accuracy_rate: number | null
  summary_issue_count: number
  high_value_miss_count: number
  feedback_needed: number
  adjacent_error_count: number
  major_error_count: number
  confusion_matrix: CalibrationMatrixCell[]
  suggestions: CalibrationSuggestion[]
}

export interface CalibrationMatrixCell {
  ai_recommendation: Recommendation
  user_recommendation: Recommendation
  count: number
}

export interface CalibrationSuggestion {
  id: string
  title: string
  evidence: string
  proposed_rule: string
  status: 'pending' | 'accepted' | 'rejected'
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
  recommendation: Recommendation | null
  ai_recommendation: Recommendation | null
  user_recommendation: Recommendation | null
  discovery_type: string | null
}

export interface ContentDetail extends ContentSummary {
  markdown: string
  triage: TriageResult | null
  content_analysis: ContentAnalysisResult | null
  personal_evaluation: PersonalEvaluationResult | null
  feedback: ArticleFeedback | null
}

export interface CaptureAccepted {
  content_id: string
  analysis_id: string
  status: AnalysisStatus
  detail_url: string
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

/** 使用管理员账号登录；令牌由调用页面确认后保存。 */
export async function login(username: string, password: string): Promise<LoginResult> {
  const response = await fetch('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  return apiResponse<LoginResult>(response)
}

/** 获取当前账户及是否仍使用初始密码。 */
export async function getCurrentUser(): Promise<CurrentUser> {
  const response = await authenticatedFetch('/api/v1/auth/me')
  return apiResponse<CurrentUser>(response)
}

/** 修改密码后服务端会撤销所有设备的旧令牌。 */
export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  const response = await authenticatedFetch('/api/v1/auth/change-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  })
  await apiResponse<{ message: string }>(response)
  clearAccessToken()
}

/** 撤销当前 Web 会话；网络失败时也清除本地令牌。 */
export async function logout(): Promise<void> {
  try {
    const response = await authenticatedFetch('/api/v1/auth/logout', { method: 'POST' })
    await apiResponse<{ message: string }>(response)
  } catch {
    // 后端暂时不可用时仍允许用户清除本地会话并返回登录页。
  } finally {
    clearAccessToken()
  }
}

/** 获取插件 Key 的非敏感状态。 */
export async function getPluginKeyStatus(): Promise<PluginKeyStatus> {
  const response = await authenticatedFetch('/api/v1/plugin-key')
  return apiResponse<PluginKeyStatus>(response)
}

/** 生成并替换唯一插件 Key；完整值只在本次响应中返回。 */
export async function generatePluginKey(): Promise<GeneratedPluginKey> {
  const response = await authenticatedFetch('/api/v1/plugin-key', { method: 'POST' })
  return apiResponse<GeneratedPluginKey>(response)
}

/** 撤销插件 Key，使已配置的插件立即停止提交。 */
export async function revokePluginKey(): Promise<void> {
  const response = await authenticatedFetch('/api/v1/plugin-key', { method: 'DELETE' })
  await apiResponse<{ message: string }>(response)
}

/** 获取最近采集的内容及最新分析状态。 */
export async function getContents(): Promise<ContentSummary[]> {
  const response = await authenticatedFetch('/api/v1/contents')
  return apiResponse<ContentSummary[]>(response)
}

/** 获取单篇内容的原始 Markdown 与完整分析结果。 */
export async function getContent(contentId: string): Promise<ContentDetail> {
  const response = await authenticatedFetch(`/api/v1/contents/${encodeURIComponent(contentId)}`)
  return apiResponse<ContentDetail>(response)
}

/** 将失败的分析清空阶段结果后重新放回 Worker 队列。 */
export async function retryAnalysis(analysisId: string): Promise<CaptureAccepted> {
  const response = await authenticatedFetch(`/api/v1/analyses/${encodeURIComponent(analysisId)}/retry`, {
    method: 'POST',
  })
  return apiResponse<CaptureAccepted>(response)
}

/** 获取初始问卷和当前评测模式。 */
export async function getProfile(): Promise<UserProfile> {
  const response = await authenticatedFetch('/api/v1/profile')
  return apiResponse<UserProfile>(response)
}

/** 保存用户明确填写的画像，不从行为中自动推断。 */
export async function updateProfile(profile: ProfileUpdate): Promise<UserProfile> {
  const response = await authenticatedFetch('/api/v1/profile', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(profile),
  })
  return apiResponse<UserProfile>(response)
}

/** 新增或更新一次分析对应的阅读后评价。 */
export async function saveFeedback(
  analysisId: string,
  feedback: FeedbackUpdate,
): Promise<ArticleFeedback> {
  const response = await authenticatedFetch(`/api/v1/analyses/${encodeURIComponent(analysisId)}/feedback`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(feedback),
  })
  return apiResponse<ArticleFeedback>(response)
}

/** 获取评测模式积累的基础校准指标。 */
export async function getCalibrationStats(): Promise<CalibrationStats> {
  const response = await authenticatedFetch('/api/v1/calibration/stats')
  return apiResponse<CalibrationStats>(response)
}

/** 记录候选阅读规则的人工决定；该决定不会直接改写画像或 Prompt。 */
export async function decideCalibrationSuggestion(
  suggestionId: string,
  decision: 'accepted' | 'rejected',
): Promise<CalibrationSuggestion> {
  const response = await authenticatedFetch(
    `/api/v1/calibration/suggestions/${encodeURIComponent(suggestionId)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision }),
    },
  )
  return apiResponse<CalibrationSuggestion>(response)
}
