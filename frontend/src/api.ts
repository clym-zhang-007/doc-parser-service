export interface JobCreateResponse {
  job_id: string;
  status: string;
  created_at: string;
}

export interface JobStatusResponse {
  job_id: string;
  status: string;
  created_at: string;
  updated_at?: string | null;
}

export interface BlockItem {
  type?: string;
  text?: string;
  index?: number;
}

export interface ResultPayload {
  document?: { title?: string; text?: string } | null;
  blocks?: BlockItem[];
  meta?: Record<string, unknown>;
  error?: { code?: string; message?: string } | null;
}

export interface JobResultResponse {
  job_id: string;
  status: string;
  result?: ResultPayload | null;
  error?: string | null;
}

async function readErrorMessage(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const data = JSON.parse(text) as {
      error?: { code?: string; message?: string };
      detail?: unknown;
    };
    if (data.error?.message) {
      const c = data.error.code;
      return c ? `[${c}] ${data.error.message}` : data.error.message;
    }
    const d = data.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d
        .map((x: { msg?: string }) => x.msg)
        .filter(Boolean)
        .join("; ");
    }
  } catch {
    /* ignore */
  }
  return res.statusText || `HTTP ${res.status}`;
}

export async function createJob(file: File): Promise<JobCreateResponse> {
  const body = new FormData();
  body.append("file", file);
  const res = await fetch("/v1/jobs", { method: "POST", body });
  if (!res.ok) throw new Error(await readErrorMessage(res));
  return res.json() as Promise<JobCreateResponse>;
}

export async function fetchJobStatus(jobId: string): Promise<JobStatusResponse> {
  const res = await fetch(`/v1/jobs/${encodeURIComponent(jobId)}`);
  if (!res.ok) throw new Error(await readErrorMessage(res));
  return res.json() as Promise<JobStatusResponse>;
}

export async function fetchJobResult(jobId: string): Promise<JobResultResponse> {
  const res = await fetch(`/v1/jobs/${encodeURIComponent(jobId)}/result`);
  if (!res.ok) throw new Error(await readErrorMessage(res));
  return res.json() as Promise<JobResultResponse>;
}
