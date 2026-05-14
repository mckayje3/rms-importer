// API Types matching backend models

export interface ProcoreCompany {
  id: number;
  name: string;
  is_active: boolean;
}

export interface ProcoreProject {
  id: number;
  name: string;
  company_id: number;
  active: boolean;
}

export interface ProcoreStats {
  submittal_count: number;
  // null when populated via the fast pagination-header path (the common case);
  // the legacy full-fetch fallback fills these in.
  spec_section_count: number | null;
  revision_count: number | null;
  spec_sections: string[];
}

export interface RMSSubmittal {
  section: string;
  item_no: number;
  sd_no: string | null;
  description: string;
  date_in: string | null;  // Not used - dates from Transmittal Log
  qc_code: string | null;
  date_out: string | null;  // Not used - dates from Transmittal Log
  qa_code: string | null;
  status: string | null;  // RMS status (Outstanding, Complete, In Review)
  match_key: string;
  // Computed fields (mapped for Procore)
  procore_status: string | null;  // Draft, Closed, Open
  procore_type: string | null;  // SD-XX: DESCRIPTION
}

export interface RMSParseResult {
  submittals: RMSSubmittal[];
  submittal_count: number;
  spec_section_count: number;
  revision_count: number;
  errors: string[];
  warnings: string[];
}

export interface RMSSession {
  session_id: string;
  submittal_count: number;
  spec_section_count: number;
  revision_count: number;
  errors: string[];
  warnings: string[];
}

export enum ImportMode {
  FULL_MIGRATION = "full_migration",
  SYNC_FROM_RMS = "sync_from_rms",
  RECONCILE = "reconcile",
}

export enum MatchStatus {
  MATCHED = "matched",
  RMS_ONLY = "rms_only",
  PROCORE_ONLY = "procore_only",
}

export interface FieldConflict {
  field_name: string;
  rms_value: string | null;
  procore_value: string | null;
}

export interface MatchResult {
  match_key: string;
  status: MatchStatus;
  rms_index: number | null;
  procore_id: number | null;
  section: string;
  item_no: number;
  revision: number;
  title: string | null;
  conflicts: FieldConflict[];
  has_conflicts: boolean;
}

export interface MatchingSummary {
  total_rms: number;
  total_procore: number;
  matched_count: number;
  rms_only_count: number;
  procore_only_count: number;
  conflict_count: number;
  match_rate: number;
  recommended_mode: ImportMode;
  recommendation_reason: string;
}

export interface AnalyzeResponse {
  summary: MatchingSummary;
  matches: MatchResult[];
}

// Vendor Matching Types
export interface VendorSuggestion {
  vendor_id: number;
  vendor_name: string;
  score: number;
}

export interface VendorMatchResult {
  input_name: string;
  vendor_id: number | null;
  vendor_name: string | null;
  match_score: number;
  exact_match: boolean;
  suggestions: VendorSuggestion[];
}

export interface MatchContractorsResponse {
  total_contractors: number;
  matched_count: number;
  unmatched_count: number;
  vendor_count: number;
  results: Record<string, VendorMatchResult>;
}

export interface ProcoreVendor {
  id: number;
  name: string;
  company: string | null;
  is_active: boolean;
}

export interface ContractorMapping {
  has_mapping: boolean;
  total_sections: number;
  mappings: Record<string, { name: string; vendor_id: number | null }>;
}

// Sync Types
export interface SyncFieldChange {
  field: string;
  old_value: string | null;
  new_value: string | null;
}

export interface SyncCreateAction {
  key: string;
  section: string;
  item_no: number;
  revision: number;
  title: string;
  type: string | null;
}

export interface SyncUpdateAction {
  key: string;
  procore_id: number;
  changes: SyncFieldChange[];
}

export interface SyncFlagAction {
  key: string;
  procore_id: number;
  reason: string;
}

export interface SyncFileUploadAction {
  filename: string;
  submittal_keys: string[];
}

export interface SyncPlan {
  mode: "full_migration" | "incremental";
  creates: SyncCreateAction[];
  updates: SyncUpdateAction[];
  flags: SyncFlagAction[];
  file_uploads: SyncFileUploadAction[];
  files_already_uploaded: number;
  has_changes: boolean;
  summary: string;
}

export interface BaselineInfo {
  has_baseline: boolean;
  last_sync: string | null;
  submittal_count: number;
  file_count: number;
}

export interface SyncAnalysisResponse {
  baseline: BaselineInfo;
  plan: SyncPlan;
  summary: string;
}

export interface SyncExecuteResponse {
  status: string;
  created: number;
  updated: number;
  files_uploaded: number;
  flagged: number;
  errors: string[];
  baseline_updated: boolean;
  update_job_id?: string;
}

// File Upload Job Types
export interface FileFilterResponse {
  new_files: string[];
  already_uploaded: string[];
  unmapped_files: string[];
  total_checked: number;
}

export type JobType = "submittals" | "rfi" | "daily_logs" | "observations";

export interface FileJobStatus {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  total_files: number;
  uploaded_files: number;
  errors: string[];
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  result_summary: {
    uploaded: number;
    total: number;
    errors: number;
    created?: number;
    updated?: number;
    files?: number;
  } | null;
  // Module that produced this job. Older rows (pre-job_type) are null.
  job_type: JobType | null;
}

// Tool Selection
export type ToolType = "submittals" | "rfis" | "daily-logs" | "observations";

// RFI Types
export interface RMSRFI {
  rfi_number: string;
  number: number;
  subject: string;
  date_requested: string | null;
  date_received: string | null;
  date_answered: string | null;
  requester_name: string | null;
  responder_name: string | null;
  is_answered: boolean;
  question_preview: string;
  has_response: boolean;
}

export interface RFISession {
  session_id: string;
  total_count: number;
  answered_count: number;
  outstanding_count: number;
  errors: string[];
  warnings: string[];
}

export interface RFICreateAction {
  rfi_number: string;
  number: number;
  subject: string;
  is_answered: boolean;
}

export interface RFIResponseAction {
  rfi_number: string;
  number: number;
  procore_rfi_id: number;
  response_body: string;
  date_answered: string | null;
}

export interface RFISyncPlan {
  creates: RFICreateAction[];
  response_updates: RFIResponseAction[];
  already_exist: number;
  total_rms: number;
  has_changes: boolean;
  summary: string;
}

export interface RFIAnalyzeResponse {
  plan: RFISyncPlan;
  summary: string;
}

export interface RFIExecuteResponse {
  status: string;
  created: number;
  replies_added: number;
  errors: string[];
  job_id: string | null;
}

export interface RFIJobStatus {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  total: number;
  created: number;
  replies_added: number;
  responses_added: number;
  errors: string[];
}

// Daily Log Types
export interface DailyLogSession {
  session_id: string;
  equipment_count: number;
  labor_count: number;
  narrative_count: number;
  date_count: number;
  errors: string[];
  warnings: string[];
}

export interface DailyLogSyncPlan {
  equipment_creates: number;
  labor_creates: number;
  narrative_creates: number;
  already_exist: number;
  total_creates: number;
  has_changes: boolean;
  summary: string;
  unmatched_vendors: string[];
}

export interface DailyLogAnalyzeResponse {
  plan: DailyLogSyncPlan;
  summary: string;
  vendor_map: Record<string, number | null>;
}

export interface DailyLogExecuteResponse {
  status: string;
  job_id: string | null;
}

export interface DailyLogJobStatus {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  total: number;
  completed: number;
  equipment_created: number;
  labor_created: number;
  narratives_created: number;
  errors: string[];
}

// Observations Types
export interface ObservationsSession {
  session_id: string;
  total_count: number;
  open_count: number;
  closed_count: number;
  locations: string[];
  project_name: string | null;
  report_date: string | null;
  errors: string[];
  warnings: string[];
}

export interface ObservationType {
  id: number;
  name: string;
  category: string | null;
}

export interface ObservationSyncPlan {
  creates: number;
  already_exist: number;
  total_rms: number;
  has_changes: boolean;
  summary: string;
  locations_to_create: string[];
  observation_types: ObservationType[];
}

export interface ObservationsAnalyzeResponse {
  plan: ObservationSyncPlan;
  summary: string;
  location_map: Record<string, number | null>;
}

export interface ObservationsExecuteResponse {
  status: string;
  job_id: string | null;
}

export interface ObservationsJobStatus {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  total: number;
  completed: number;
  observations_created: number;
  locations_created: number;
  errors: string[];
}

// App State
export type AppStep =
  | "auth"
  | "select-project"
  | "project-setup"
  | "select-tool"
  | "upload-rms"
  | "analyze"
  | "sync-review"
  | "review"
  | "import"
  | "rfi-upload"
  | "rfi-review"
  | "daily-logs-upload"
  | "daily-logs-review"
  | "observations-upload"
  | "observations-review"
  | "complete";

export interface AppState {
  step: AppStep;
  isAuthenticated: boolean;
  company: ProcoreCompany | null;
  project: ProcoreProject | null;
  rmsSession: RMSSession | null;
  analysis: AnalyzeResponse | null;
  selectedMode: ImportMode | null;
}

// Project Setup Types
export interface ProcoreCustomField {
  id: number;
  label: string;
  data_type: string;
  field_key: string;
}

export interface ProjectConfigData {
  status_mode: "qa_code" | "rms_status";
  status_map: Record<string, string>;
  sd_type_map: Record<string, string>;
  custom_fields: Record<string, string>;
  setup_completed: boolean;
}

export interface ProjectDiscovery {
  custom_fields: ProcoreCustomField[];
  statuses: string[];
  has_existing_config: boolean;
  existing_config: ProjectConfigData | null;
  suggested_config: ProjectConfigData;
}

export interface ProjectConfig {
  project_id: string;
  company_id: string;
  config_data: ProjectConfigData;
  created_at: string;
  updated_at: string;
}
