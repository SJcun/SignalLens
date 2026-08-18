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

export interface AnalysisQueueState {
  stage:
    | 'triage'
    | 'analyze'
    | 'persist_claims'
    | 'retrieve_memory'
    | 'compare'
    | 'evaluate'
    | 'completed'
  execution_mode: 'scheduled' | 'immediate'
  waiting_for_schedule: boolean
  next_eligible_at: string | null
}

export interface AnalysisWindow {
  start: string
  end: string
}

export interface AnalysisSchedule {
  enabled: boolean
  windows: AnalysisWindow[]
  timezone: 'Asia/Shanghai'
  currently_allowed: boolean
  next_window_start: string | null
  scheduled_job_count: number
  updated_at: string
}
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

export interface ContentMapItem {
  section_ref: string | null
  title: string
  summary: string
}

export type ClaimType =
  | 'fact'
  | 'interpretation'
  | 'opinion'
  | 'prediction'
  | 'recommendation'
  | 'definition'
export type ClaimRole = 'core' | 'supporting' | 'detail'
export type ChangeSignal = 'none' | 'temporal' | 'version' | 'replacement' | 'deprecation'
export type PrimaryRelation =
  | 'duplicate'
  | 'extends'
  | 'complements'
  | 'contradicts'
  | 'updates'
  | 'new'

export interface ContentClaim {
  claim_id: string | null
  claim: string
  claim_type: ClaimType
  claim_role: ClaimRole
  change_signal: ChangeSignal
  section_ref: string | null
  evidence: string[]
  verification: 'supported_in_content' | 'unverified' | 'opinion'
  topics: string[]
  entities: string[]
}

export interface ContentAnalysisResult {
  one_sentence_summary: string
  summary: string
  content_map: ContentMapItem[]
  key_points: string[]
  claims: ContentClaim[]
  counterarguments: string[]
  limitations: string[]
  unresolved_questions: string[]
  unverified_claims: string[]
}

export interface ReadingPlanItem {
  section_ref: string | null
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
  queue: AnalysisQueueState
  /** Inbox 使用的简短认知差异摘要；Compare 未完成或旧分析时为空。 */
  delta_summary: {
    cognitive_gain_count: number
    known_duplicate_count: number
    retrieval_context_status: 'sufficient' | 'partial' | 'insufficient' | null
  } | null
}

export interface TranslationBlock {
  id: string
  kind: 'heading' | 'paragraph' | 'list' | 'quote' | 'table' | 'code' | 'image' | 'separator'
  source_markdown: string
  translated_markdown: string | null
  shared: boolean
  /** 块在原文中的行号范围（零起点、左闭右开），与 section_index 口径一致。 */
  start_line: number | null
  end_line: number | null
}

export interface ContentTranslation {
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  source_language: string
  target_language: 'zh-CN'
  completed_blocks: number
  total_blocks: number
  blocks: TranslationBlock[]
  model: string | null
  prompt_version: string
  last_error: string | null
  created_at: string
  completed_at: string | null
}

export interface SectionRef {
  section_ref: string
  level: number
  title: string
  order: number
  start_line: number
  end_line: number
}

export interface SectionIndex {
  primary_heading_level: number
  sections: SectionRef[]
}

export interface CompareMatch {
  memory_revision_id: string
  candidate_kind: 'current' | 'historical'
  relation: Exclude<PrimaryRelation, 'new'>
  reason: string
}

export interface CompareRelation {
  current_claim_id: string
  primary_relation: PrimaryRelation
  matches: CompareMatch[]
  added_information: string | null
  conflict_summary: string | null
  reason: string
  confidence: 'low' | 'medium' | 'high'
}

export interface ClaimCorrection {
  id: string
  analysis_id: string
  content_claim_id: string
  correction_type: 'primary_relation' | 'claim_role'
  original_value: string
  corrected_value: string
  matched_memory_revision_ids: string[]
  evidence_status: 'complete' | 'incomplete' | 'not_applicable'
  reason: string | null
  created_at: string
}

export interface CognitiveDelta {
  retrieval_context: Record<string, unknown>
  relations: CompareRelation[]
  /** 应用最新用户纠错后的展示值；原始 relations 保持不变。 */
  effective_relations: CompareRelation[]
  claim_corrections: ClaimCorrection[]
  derived_summary: Record<string, unknown>
}

export interface ContentDetail extends ContentSummary {
  markdown: string
  source_language: string
  translation: ContentTranslation | null
  triage: TriageResult | null
  content_analysis: ContentAnalysisResult | null
  personal_evaluation: PersonalEvaluationResult | null
  feedback: ArticleFeedback | null
  /** 系统主章节清单；正文快照变化后为 null，避免引用错位。 */
  section_index: SectionIndex | null
  /** 是否启用顺序式引导阅读流；false 时正文整体退回完整原文。 */
  guided_flow_available: boolean
  /** 本次分析的行级 Claims；旧分析为空时回退读取 content_analysis.claims。 */
  claims: ContentClaim[] | null
  /** 本次分析的认知差异；Compare 未完成、失败或旧分析时为空。 */
  cognitive_delta: CognitiveDelta | null
  /** 代码计算的召回上下文状态；旧分析或未执行 Compare 时为空。 */
  retrieval_context_status: 'sufficient' | 'partial' | 'insufficient' | null
}

export interface CaptureAccepted {
  content_id: string
  analysis_id: string
  status: AnalysisStatus
  detail_url: string
  queue: AnalysisQueueState
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

/** 幂等创建或重试正文翻译任务；已有有效译文时直接返回缓存。 */
export async function translateContent(contentId: string): Promise<ContentTranslation> {
  const response = await authenticatedFetch(
    `/api/v1/contents/${encodeURIComponent(contentId)}/translation`,
    { method: 'POST' },
  )
  return apiResponse<ContentTranslation>(response)
}

/** 将失败的分析清空阶段结果后重新放回 Worker 队列。 */
export async function retryAnalysis(analysisId: string): Promise<CaptureAccepted> {
  const response = await authenticatedFetch(`/api/v1/analyses/${encodeURIComponent(analysisId)}/retry`, {
    method: 'POST',
  })
  return apiResponse<CaptureAccepted>(response)
}

/** 将等待或进行中的任务标记为用户明确要求立即整理。 */
export async function runAnalysisNow(analysisId: string): Promise<CaptureAccepted> {
  const response = await authenticatedFetch(
    `/api/v1/analyses/${encodeURIComponent(analysisId)}/run-now`,
    { method: 'POST' },
  )
  return apiResponse<CaptureAccepted>(response)
}

/** 获取 AI 整理总开关、每日窗口和当前等待数量。 */
export async function getAnalysisSchedule(): Promise<AnalysisSchedule> {
  const response = await authenticatedFetch('/api/v1/analysis-schedule')
  return apiResponse<AnalysisSchedule>(response)
}

/** 保存完整整理设置；总开关切换也通过此接口立即持久化。 */
export async function updateAnalysisSchedule(
  payload: Pick<AnalysisSchedule, 'enabled' | 'windows'>,
): Promise<AnalysisSchedule> {
  const response = await authenticatedFetch('/api/v1/analysis-schedule', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return apiResponse<AnalysisSchedule>(response)
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

export type AwarenessState = 'known' | 'uncertain'
export type MemoryStance = 'accept' | 'reject' | 'mixed' | 'undecided' | 'not_applicable'
export type MemoryLifecycle = 'active' | 'obsolete'
export type MemoryConfidence = 'low' | 'medium' | 'high'

export interface MemoryRevision {
  id: string
  cognitive_memory_id: string
  version: number
  statement: string
  awareness_state: AwarenessState
  stance: MemoryStance
  lifecycle: MemoryLifecycle
  confidence: MemoryConfidence
  topics: string[]
  entities: string[]
  source_type: 'manual' | 'claim_feedback' | 'accepted_proposal'
  created_at: string
  confirmed_at: string | null
}

export interface MemorySummary {
  id: string
  current_revision: MemoryRevision | null
  created_at: string
  revision_count: number
}

export interface MemoryConfirmationEvent {
  id: string
  confirmation_type:
    | 'already_known'
    | 'learned_now'
    | 'awareness_confirmed'
    | 'stance_confirmed'
    | 'source_confirmed'
  source_type: 'manual' | 'claim_feedback' | 'accepted_proposal'
  content_claim_id: string | null
  source_feedback_id: string | null
  source_proposal_id: string | null
  created_at: string
}

export interface MemoryDetail extends MemorySummary {
  revisions: MemoryRevision[]
  confirmation_events: MemoryConfirmationEvent[]
}

export interface MemoryWriteResult {
  outcome: 'confirmed' | 'revised' | 'created' | 'proposal'
  memory: MemorySummary | null
  proposal_id: string | null
  match_source: 'exact_text' | 'cognitive_delta' | 'entity_topic' | 'none'
  reason: string
}

export type MemoryProposalAction =
  | 'CREATE'
  | 'REVISE'
  | 'MARK_OBSOLETE'
  | 'REACTIVATE'
  | 'RESOLVE_MATCH'

export interface MemoryProposal {
  id: string
  action: MemoryProposalAction
  target_memory_id: string | null
  expected_current_revision_id: string | null
  candidate_memory_revision_ids: string[]
  proposed_statement: string | null
  proposed_awareness_state: string | null
  proposed_stance: string | null
  proposed_lifecycle: string | null
  evidence_claim_ids: string[]
  reason: string | null
  status: 'pending' | 'accepted' | 'rejected' | 'stale'
  created_at: string
  decided_at: string | null
}

export interface CurrentUserState {
  active_goals: string[]
  active_questions: string[]
  focus_context: string | null
  available_minutes: number | null
  preferred_depth: 'quick' | 'balanced' | 'deep' | null
  exploration_level: 'low' | 'medium' | 'high' | null
  valid_until: string | null
  updated_at: string
}

export type CurrentUserStateUpdate = Omit<CurrentUserState, 'updated_at'>

/** 获取全部认知记忆的逻辑身份与当前版本。 */
export async function getMemories(): Promise<MemorySummary[]> {
  const response = await authenticatedFetch('/api/v1/memory')
  return apiResponse<MemorySummary[]>(response)
}

/** 获取单个 Memory 的完整不可变历史与确认记录。 */
export async function getMemory(memoryId: string): Promise<MemoryDetail> {
  const response = await authenticatedFetch(`/api/v1/memory/${encodeURIComponent(memoryId)}`)
  return apiResponse<MemoryDetail>(response)
}

/** 手工录入认知；服务端先执行 Memory Match 再决定确认、修订或新建。 */
export async function createMemoryEntry(payload: {
  statement: string
  awareness_state: AwarenessState
  stance: MemoryStance
  lifecycle?: MemoryLifecycle
  confidence?: MemoryConfidence
  topics?: string[]
  entities?: string[]
}): Promise<MemoryWriteResult> {
  const response = await authenticatedFetch('/api/v1/memory', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return apiResponse<MemoryWriteResult>(response)
}

/** 为已有 Memory 追加 Revision；期望版本不匹配时后端返回冲突。 */
export async function appendMemoryRevision(
  memoryId: string,
  payload: {
    expected_current_revision_id: string
    statement?: string | null
    awareness_state?: AwarenessState | null
    stance?: MemoryStance | null
    lifecycle?: MemoryLifecycle | null
    confidence?: MemoryConfidence | null
  },
): Promise<MemoryWriteResult> {
  const response = await authenticatedFetch(
    `/api/v1/memory/${encodeURIComponent(memoryId)}/revisions`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return apiResponse<MemoryWriteResult>(response)
}

/** 获取等待用户处理的 Memory 修改建议。 */
export async function getMemoryProposals(): Promise<MemoryProposal[]> {
  const response = await authenticatedFetch('/api/v1/memory/proposals')
  return apiResponse<MemoryProposal[]>(response)
}

/** 接受或拒绝 Memory 修改建议；RESOLVE_MATCH 合并时指定目标 Memory。 */
export async function decideMemoryProposal(
  proposalId: string,
  decision: 'accepted' | 'rejected',
  mergeMemoryId?: string | null,
): Promise<MemoryProposal> {
  const response = await authenticatedFetch(
    `/api/v1/memory/proposals/${encodeURIComponent(proposalId)}/decision`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, merge_memory_id: mergeMemoryId ?? null }),
    },
  )
  return apiResponse<MemoryProposal>(response)
}

/** 获取用户显式编辑的当前阅读状态。 */
export async function getCurrentUserState(): Promise<CurrentUserState> {
  const response = await authenticatedFetch('/api/v1/user-state')
  return apiResponse<CurrentUserState>(response)
}

/** 保存当前阅读状态；不根据浏览行为自动推断。 */
export async function updateCurrentUserState(
  payload: CurrentUserStateUpdate,
): Promise<CurrentUserState> {
  const response = await authenticatedFetch('/api/v1/user-state', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return apiResponse<CurrentUserState>(response)
}

export interface ClaimFeedbackResult {
  outcome: 'confirmed' | 'revised' | 'created' | 'proposal'
  memory_id: string | null
  proposal_id: string | null
  match_source: string
  reason: string
}

/** 对具体 Claim 提交知晓 / 立场确认，进入 Memory Match 流程。 */
export async function submitClaimFeedback(
  analysisId: string,
  claimId: string,
  payload: {
    awareness?: AwarenessState | null
    stance?: MemoryStance | null
    confirmation_type?: 'already_known' | 'learned_now' | 'awareness_confirmed' | 'stance_confirmed' | null
    root_cause?: string | null
  },
): Promise<ClaimFeedbackResult> {
  const response = await authenticatedFetch(
    `/api/v1/analyses/${encodeURIComponent(analysisId)}/claims/${encodeURIComponent(claimId)}/feedback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return apiResponse<ClaimFeedbackResult>(response)
}

/** 提交 primary_relation / claim_role 高级纠错；原始值与纠正值都保留。 */
export async function submitClaimCorrection(
  analysisId: string,
  claimId: string,
  payload: {
    correction_type: 'primary_relation' | 'claim_role'
    corrected_value: string
    matched_memory_revision_ids?: string[]
    reason?: string | null
  },
): Promise<ClaimCorrection> {
  const response = await authenticatedFetch(
    `/api/v1/analyses/${encodeURIComponent(analysisId)}/claims/${encodeURIComponent(claimId)}/correction`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  return apiResponse<ClaimCorrection>(response)
}

export interface CompareRunDetail {
  id: string
  analysis_id: string
  status: AnalysisStatus
  current_claim_ids: string[]
  current_memory_candidate_revision_ids: string[]
  historical_memory_candidate_revision_ids: string[]
  retrieval_context: Record<string, unknown>
  delta: CognitiveDelta | null
  model: string | null
  prompt_version: string
  last_error: string | null
  created_at: string
  completed_at: string | null
}

/** 获取一次 Compare 的完整输入与结果，用于诊断。 */
export async function getCompareRun(analysisId: string): Promise<CompareRunDetail> {
  const response = await authenticatedFetch(
    `/api/v1/analyses/${encodeURIComponent(analysisId)}/compare`,
  )
  return apiResponse<CompareRunDetail>(response)
}

/** 单独重试失败的 Compare；不重跑 Evaluate，不改写历史 Delta。 */
export async function retryCompare(analysisId: string): Promise<{ message: string }> {
  const response = await authenticatedFetch(
    `/api/v1/analyses/${encodeURIComponent(analysisId)}/retry-compare`,
    { method: 'POST' },
  )
  return apiResponse<{ message: string }>(response)
}
