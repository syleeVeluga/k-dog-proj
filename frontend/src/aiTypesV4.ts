import type { BasicResultViewV4 } from './BasicResultsV4';

export type AiStageV4 = {
  model: 'gemini-3.8-flash'; prompt: string; input_variant: 'ai' | 'original'; processing_mode: 'static' | 'agentic';
  fps: number | null; media_resolution: 'low' | 'medium' | 'high'; thinking_level: 'low' | 'medium' | 'high'; max_output_tokens: number;
};
export type AiPipelineV4 = { groups: Record<string, AiStageV4>; raw_observation_scope_confirmed: boolean; max_attempts: number; max_ai_calls: number; max_schema_repairs: number };
export type AiGroupV4 = { windows: string[]; codes: string[]; usage: string; modality: string; whole: boolean; opportunity_codes: string[]; pending: boolean; provider_call: boolean };
export type AiTrialV4 = { trial_id: string; version: string; group: string; mode: 'schema'; created_at: string; status: 'schema_valid'; sample: 'synthetic-s1'; usage: { provider_calls: number }; output: unknown };
export type AiSettingsViewV4 = {
  active_version: string; config: AiPipelineV4; groups: Record<string, AiGroupV4>;
  versions: { version: string; created_at: string; actor: string }[]; trials: AiTrialV4[];
  planned_provider_calls: number; price_estimate: string | null; judgement_status: 'policy_pending_D04' | 'implemented_professor_test_pending'; provider_trial_status: 'deferred_S16';
};
export type AiDifferenceV4 = { active_version: string; version: string; config: AiPipelineV4; diff: string };
export type AiReadinessV4 = { active_version: string; planned_provider_calls: number; enabled: boolean; judgement_status: 'policy_pending_D04' | 'implemented_professor_test_pending' };
export type AiStepV4 = {
  stage: string; key: string; attempt: number; status: string; code: string | null; billing_uncertain: boolean; call_reserved: boolean; remote_cleanup_pending: boolean;
  reused: boolean; timing: Record<string, number>; token_meters: Record<string, number>; input_tokens: number | null; output_tokens: number | null; total_tokens: number | null; cost_usd: number | null;
};
export type AiRunV4 = {
  run_id: string; case_id: string; session_id: string; kind: 's1'; input_revision: number; status: string; updated_at: string;
  outdated: boolean; failure_code: string | null; result_available: boolean; steps: AiStepV4[];
  planned_provider_calls: number; reserved_calls: number; max_ai_calls: number; judgement_status: 'policy_pending_D04' | 'implemented_professor_test_pending';
};
export type AiBasicResultV4 = BasicResultViewV4['document'] & { result_id: string };
