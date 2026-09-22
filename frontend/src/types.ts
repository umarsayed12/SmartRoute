// Mirror the backend's chat, history, statistics, and administration contracts.
export type TierName = 'small' | 'medium' | 'large'
export type RoutingMode = 'heuristic' | 'learned' | 'forced'
export type RunMode = 'auto' | TierName
export type PlaygroundMode = RunMode | 'compare'

export interface ClientConfig {
  mode: 'local' | 'preview' | 'hosted'
  auth_url: string | null
  inference_enabled: boolean
  retention_days?: number
}

export interface WorkspaceAccount {
  workspace: { id: string; name: string; plan: string }
  user: { id: string; email: string; display_name: string; email_verified: boolean } | null
  auth_type: 'session' | 'api_key'
}

export interface GatewayKey {
  id: string
  name: string
  key_prefix: string
  created_at: string
  last_used_at?: string | null
  expires_at: string | null
  revoked_at?: string | null
}

export interface PlaygroundAnswer {
  mode: RunMode
  state: 'queued' | 'loading' | 'done' | 'error' | 'cancelled'
  response?: ChatCompletion
  error?: string
}

export interface PlaygroundTurn {
  id: string
  prompt: string
  mode: PlaygroundMode
  messages: ChatMessage[]
  answers: PlaygroundAnswer[]
  selectedMode?: RunMode
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
}

export interface RoutingInfo {
  request_id: string
  tier_chosen: TierName
  tier_final: TierName
  escalated: boolean
  confidence: number
  reason: string
  routing_mode: RoutingMode
  latency_ms: number
  actual_cost_usd: number
  reference_cost_usd: number
}

export interface ChatCompletion {
  id: string
  object: 'chat.completion'
  created: number
  model: string
  choices: { index: number; message: ChatMessage; finish_reason: 'stop' | 'length' }[]
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
  smartroute: RoutingInfo
}

export interface Feedback {
  request_id: string
  score: 1 | -1
  note: string | null
}

export interface Health {
  status: string
  tiers: TierName[]
  ollama: boolean
  model_file_present: boolean
}

export interface Tier {
  name: TierName
  provider: 'ollama' | 'openai_compatible' | 'openai' | 'anthropic'
  model: string
  base_url: string
  input_price_per_1k: number
  output_price_per_1k: number
  enabled: boolean
  reachable: boolean
}

export interface RuntimeSettings {
  confidence_threshold: number
  max_escalations: number
  reference_input_price_per_1k: number
  reference_output_price_per_1k: number
  routing_mode_preference: 'auto' | 'heuristic_only' | 'learned_only'
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface RequestSummary extends Omit<RoutingInfo, 'request_id' | 'actual_cost_usd'> {
  id: string
  created_at: string
  prompt_preview: string
  prompt_tokens: number
  completion_tokens: number
  feedback: 1 | -1 | null
  feedback_note: string | null
  source: 'api' | 'playground' | 'testlab' | 'sdk'
  status?: 'completed' | 'failed'
  error_code?: string | null
  actual_cost_usd: number | null
}

export interface RequestDetail extends RequestSummary {
  prompt_full: string
  answer_full: string
  features_json: string
  attempts?: { id: string; sequence: number; kind: 'answer' | 'self_check'; status: 'completed' | 'failed'; error_code: string | null; tier: TierName; provider: string; model: string; prompt_tokens: number; completion_tokens: number; latency_ms: number; cost_usd: number | null; usage_details: Record<string, unknown> }[]
}

export interface ProviderCredential {
  id: string
  provider: 'openai' | 'anthropic'
  label: string
  key_suffix: string
  created_at?: string
}

export interface ConfiguredModel {
  id: string
  tier: TierName
  credential_id: string
  provider: 'openai' | 'anthropic'
  model: string
  input_price_per_1k: number
  output_price_per_1k: number
  enabled: boolean
  send_temperature: boolean
  self_check_max_tokens: number
}

export type ModelConfiguration = Omit<ConfiguredModel, 'id' | 'tier' | 'provider'>

export interface RequestFilters {
  limit?: number
  offset?: number
  tier?: TierName
  escalated?: boolean
  feedback?: -1 | 0 | 1
  search?: string
  source?: RequestSummary['source']
}

export interface Stats {
  totals: { requests: number; escalations: number; escalation_rate: number }
  cost: { actual_usd: number; reference_usd: number; saved_usd: number; saved_pct: number }
  quality: {
    feedback_count: number
    positive_rate: number | null
    by_tier: Record<TierName, { count: number; positive_rate: number | null }>
  }
  tier_distribution: Record<TierName, number>
  latency: Record<TierName, { p50: number | null; p95: number | null }>
  timeline: { date: string; requests: number; saved_usd: number; positive_rate: number | null }[]
  routing_modes: Record<RoutingMode, number>
}

export interface TrainingMetadata {
  trained: true
  trained_at: string
  n_rows: number
  accuracy: number
  classes: TierName[]
  confusion_matrix: number[][]
  evaluation: 'holdout' | 'training' | null
}

export type TrainingResult = TrainingMetadata | { trained: false; n_rows: number; message: string }
export type TrainingStatus = TrainingMetadata | { trained: false }

export interface Suite {
  id: string
  name: string
  count: number
  tier_distribution: Record<TierName, number>
  max_tokens: number
}

export interface RunSummary {
  routing_accuracy: number
  escalation_rate: number
  avg_latency_ms: number
  total_actual_usd: number
  total_reference_usd: number
  saved_pct: number
}

export interface TestLabRun {
  run_id: string
  created_at: string
  suite: string
  mode: RunMode
  prompt_count: number
  summary: RunSummary
}

export interface TestLabResult extends TestLabRun {
  results: {
    id: string
    request_id: string
    prompt: string
    expected_tier: TierName
    tier_final: TierName
    escalated: boolean
    confidence: number
    latency_ms: number
    actual_cost_usd: number
    reference_cost_usd: number
    match: boolean
  }[]
}