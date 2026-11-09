export type Decision = "PASS" | "REJECT";
export type Mode = "real" | "demo" | null;

export interface Defect {
  class_id: number;
  class_name: string;
  confidence: number;
  bbox: [number, number, number, number];
  triggered: boolean;
}

export interface Inspection {
  id: string;
  created_at: string;
  original_filename: string | null;
  decision: Decision;
  reasons: string | null;
  top_class: string | null;
  top_confidence: number | null;
  top_bbox: number[] | null;
  defect_count: number;
  model_mode: "real" | "demo";
  model_name: string;
  model_version: string;
  confidence_threshold: number;
  iou_threshold: number;
  duration_ms: number | null;
  width: number;
  height: number;
  source: "upload" | "plc_cycle" | "demo_seed";
  plc_event_id: string | null;
  defects: Defect[];
  is_demo: boolean;
  original_url: string;
  annotated_url: string;
}

export interface InspectionList {
  items: Inspection[];
  total: number;
  limit: number;
  offset: number;
}

export interface UploadResult {
  ok: boolean;
  upload_id?: string;
  filename: string;
  width?: number;
  height?: number;
  error?: string;
}

export interface AnalyzeResult {
  upload_id: string;
  ok: boolean;
  inspection?: Inspection;
  error?: string;
}

export interface Stats {
  total: number;
  passed: number;
  rejected: number;
  reject_rate: number;
  avg_duration_ms: number | null;
  defect_distribution: { class_name: string; count: number }[];
  trend: { date: string; total: number; passed: number; rejected: number }[];
  recent: { id: string; created_at: string; decision: Decision; top_class: string | null; model_mode: string; source: string }[];
  demo_records: number;
  include_demo: boolean;
  model: { mode: Mode; ready: boolean };
}

export interface DecisionRules {
  min_confidence: number;
  class_min_confidence: Record<string, number>;
  ignore_classes: string[];
  min_area_ratio: number;
  max_defects_allowed: number;
}

export interface ModelStatus {
  mode: Mode;
  requested_mode: "auto" | "real" | "demo";
  ready: boolean;
  reason: string;
  model_name: string | null;
  model_version: string | null;
  class_names: string[];
  weights_path: string;
  weights_present: boolean;
  confidence_threshold: number;
  iou_threshold: number;
  image_size: number;
  decision_rules: DecisionRules;
  metrics: Record<string, unknown> | null;
  metrics_warning?: string;
  training: Record<string, unknown> | null;
  demo_notice: string | null;
  setup_instructions: string | null;
}

export interface PlcSnapshot {
  coils: Record<string, boolean>;
  registers: Record<string, number>;
  machine_state: string;
  conveyor_running: boolean;
  estop: boolean;
  trigger: boolean;
  pass_signal: boolean;
  reject_signal: boolean;
  reject_actuator: boolean;
  inspection_result: string;
  component_status: string;
  counters: { components: number; passed: number; rejected: number };
  heartbeat: number;
  cycle_id: number;
}

export interface PlcStatus {
  simulator: boolean;
  label: string;
  target: string;
  embedded_simulator_running: boolean;
  connected: boolean;
  plc: PlcSnapshot | null;
  error: string | null;
}

export interface RegisterDoc {
  type: string;
  address: number;
  name: string;
  access: string;
  description: string;
}

export interface PlcRegisters {
  simulator: boolean;
  label: string;
  register_map: RegisterDoc[];
  values: PlcSnapshot;
}

export interface CycleResult {
  status: string;
  decision: Decision | null;
  failsafe_reject: boolean;
  inspection_id: string | null;
  plc_cycle_id: number | null;
  events: { t_ms: number; event: string; detail: string }[];
  plc_after: PlcSnapshot | null;
  duration_ms: number;
  scenario: string;
  scenario_note: string;
}

export interface PlcEvent {
  id: string;
  created_at: string;
  type: string;
  ok: boolean;
  detail: string | null;
  duration_ms: number | null;
  inspection_id: string | null;
}
