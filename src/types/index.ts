export type StepStatus = 'pending' | 'running' | 'completed' | 'failed';

export type StepKey = 'plan' | 'scope' | 'edit' | 'validate' | 'review' | 'pr';

export interface StepArtifact {
  name: string;
  type: string;
  size: string;
  description: string;
}

export interface PipelineStep {
  id: string;
  key: StepKey;
  stepNumber: number;
  name: string;
  shortDesc: string;
  detailedDesc: string;
  status: StepStatus;
  duration?: string;
  assignedAgent: string;
  agentRole: string;
  artifacts: StepArtifact[];
  progress: number; // 0 - 100
  inputs?: string[];
  outputs?: string[];
}

export type AgentStatus = 'idle' | 'running' | 'completed' | 'standby' | 'error';

export interface Agent {
  id: string;
  name: string;
  role: string;
  description: string;
  status: AgentStatus;
  model: string;
  lastActivity: string;
  lastActivityTime: string;
  totalTokens: string;
  latencyMs: number;
  successRate: string;
  avatarColor: string;
  accentColor: string;
  capabilities: string[];
  systemPromptSummary: string;
}

export type LogLevel = 'info' | 'warn' | 'error' | 'agent' | 'system' | 'success';

export interface LogEntry {
  id: string;
  timestamp: string;
  level: LogLevel;
  source: string;
  message: string;
  stepKey?: StepKey;
}

export type NavTab = 'orchestration' | 'agents' | 'runs' | 'tasks' | 'files' | 'settings';

export type BackendTaskStatus = 'pending' | 'queued' | 'planning' | 'planned' | 'scoping' | 'scoped' | 'coding' | 'coded' | 'testing' | 'tested' | 'reviewing' | 'reviewed' | 'changes_requested' | 'awaiting_approval' | 'blocked' | 'unsupported' | 'in_progress' | 'completed' | 'delivery_failed' | 'failed' | 'cancelled';

export interface TaskPlan {
  goal: string;
  subtasks: string[];
  acceptance_criteria: string[];
  risks: string[];
}

export interface TaskScope {
  summary: string;
  existing_files: string[];
  proposed_new_files: string[];
  out_of_scope: string[];
  risks: string[];
}

export interface CoderCreatedFile {
  path: string;
  bytes?: number;
  description?: string;
}

export interface CoderResult {
  status: 'coded' | 'unsupported' | 'failed';
  created_files: (CoderCreatedFile | string)[];
  summary: string;
  limitations: string[];
  error?: string | null;
}

export interface TestCaseResult {
  name: string;
  status: 'passed' | 'failed';
  duration_ms: number;
  error?: string | null;
}

export interface TesterResult {
  status: 'tested' | 'failed' | 'blocked' | 'unsupported';
  passed: number;
  failed: number;
  test_results: TestCaseResult[];
  summary: string;
  error?: string | null;
}

export type FindingSeverity = 'critical' | 'high' | 'medium' | 'low' | 'info';
export type ReviewerVerdict = 'approved' | 'changes_requested' | 'blocked';

export interface ReviewFinding {
  id: string;
  severity: FindingSeverity;
  category: string;
  title: string;
  description: string;
  file_path?: string | null;
  recommendation: string;
  evidence: string;
}

export interface ReviewerResult {
  status: 'reviewed' | 'failed' | 'blocked';
  verdict: ReviewerVerdict;
  findings: ReviewFinding[];
  summary: string;
  reviewed_files: string[];
  error?: string | null;
}

export interface TaskEvent {
  id: string;
  timestamp: string;
  source: string;
  type: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface BackendTask {
  id: string;
  description: string;
  status: BackendTaskStatus;
  plan?: TaskPlan | null;
  scope?: TaskScope | null;
  coder?: CoderResult | null;
  tester?: TesterResult | null;
  reviewer?: ReviewerResult | null;
  events?: TaskEvent[];
  error?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface ApiHealthResponse {
  status: string;
  message: string;
  timestamp: string;
}

export interface TaskItem {
  id: string;
  title: string;
  description: string;
  priority: 'low' | 'medium' | 'high' | 'critical';
  status: 'queued' | 'in_progress' | 'completed' | 'cancelled';
  createdAt: string;
  branch: string;
  assignedAgents: string[];
  currentStep: StepKey;
  source?: 'backend' | 'demo';
  rawBackendData?: BackendTask;
}

export interface AgentMetric {
  agent_name: string;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  error?: string | null;
  mode?: string | null;
  provider?: string | null;
  model?: string | null;
}

export interface LLMProviderInfo {
  provider: string;
  model: string;
  base_host: string;
  is_configured: boolean;
  fallback_enabled: boolean;
  default_planner_mode: string;
  default_coder_mode?: string;
}

export interface WorkflowRun {
  id: string;
  task_id: string;
  run_number: number;
  status: BackendTaskStatus;
  started_at: string;
  completed_at?: string | null;
  duration_ms?: number | null;
  error?: string | null;
  plan?: TaskPlan | null;
  scope?: TaskScope | null;
  coder?: CoderResult | null;
  tester?: TesterResult | null;
  reviewer?: ReviewerResult | null;
  events?: TaskEvent[];
  agent_metrics?: AgentMetric[];
}

export interface WorkflowRunListResponse {
  task_id: string;
  total_runs: number;
  runs: WorkflowRun[];
}

export interface SystemStats {
  activeRuns: number;
  completedTasks: number;
  avgPipelineTime: string;
  agentUptime: string;
  totalTokensProcessed: string;
}

