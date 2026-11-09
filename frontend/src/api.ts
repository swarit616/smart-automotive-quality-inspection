import type {
  AnalyzeResult, CycleResult, InspectionList, Inspection, ModelStatus, PlcEvent, PlcRegisters, PlcStatus, Stats, UploadResult,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, public kind: string, message: string) {
    super(message);
  }
}

const BASE = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, init);
  } catch {
    throw new ApiError(0, "network", "Cannot reach the inspection backend. Is it running?");
  }
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!res.ok) {
    const b = (body ?? {}) as { error?: string; detail?: unknown };
    let detail = typeof b.detail === "string" ? b.detail : Array.isArray(b.detail) ? b.detail.map((d: { msg?: string }) => d.msg).join("; ") : res.statusText;
    if (res.status === 401 || res.status === 403) {
      detail = "Control actions are restricted: use the dashboard from localhost or configure API_KEY on the proxy. (" + detail + ")";
    }
    throw new ApiError(res.status, b.error ?? "http_error", detail);
  }
  return body as T;
}

const json = (method: string, data?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: data === undefined ? undefined : JSON.stringify(data),
});

export const api = {
  stats: (includeDemo: boolean) => request<Stats>(`/dashboard/stats?include_demo=${includeDemo}`),
  seedDemo: (count = 24) => request<{ created: number }>("/demo/seed", json("POST", { count })),
  upload: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return request<{ results: UploadResult[] }>("/inspection/upload", { method: "POST", body: fd });
  },
  analyze: (uploadIds: string[], confidence?: number, iou?: number) =>
    request<{ results: AnalyzeResult[]; mode: string }>("/inspection/analyze", json("POST", { upload_ids: uploadIds, confidence, iou })),
  inspection: (id: string) => request<Inspection>(`/inspection/${encodeURIComponent(id)}`),
  inspections: (params: Record<string, string | number | boolean | undefined>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
    return request<InspectionList>(`/inspections?${qs.toString()}`);
  },
  modelStatus: () => request<ModelStatus>("/model/status"),
  modelConfig: (cfg: Record<string, unknown>) => request<ModelStatus>("/model/config", json("POST", cfg)),
  plcStatus: () => request<PlcStatus>("/plc/status"),
  plcConnect: () => request<PlcStatus>("/plc/connect", json("POST", {})),
  plcDisconnect: () => request<PlcStatus>("/plc/disconnect", json("POST")),
  plcRegisters: () => request<PlcRegisters>("/plc/registers"),
  plcEvents: () => request<{ items: PlcEvent[] }>("/plc/events?limit=25"),
  plcCycle: (scenario: "normal" | "defective") => request<CycleResult>("/plc/simulate-cycle", json("POST", { scenario })),
  plcEstop: (active: boolean) => request<PlcStatus>("/plc/emergency-stop", json("POST", { active })),
};
