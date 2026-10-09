import type {
  FraudCase,
  TransactionEvent,
  InvestigationAnalysisRequest,
  InvestigationAnalysisResponse,
  GraphManifest,
} from "../../types/index.ts";

export class ApiError extends Error {
  public status: number;
  public detail: string;
  public payload?: unknown;

  constructor(status: number, detail: string, payload?: unknown) {
    super(`API Error [${status}]: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.payload = payload;
  }
}

export class ApiClient {
  private baseUrl: string;

  constructor(baseUrl?: string) {
    this.baseUrl = (
      baseUrl ||
      process.env.NEXT_PUBLIC_API_BASE_URL ||
      "http://localhost:8000"
    ).replace(/\/+$/, "");
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;
    const headers = new Headers(options.headers);
    if (!headers.has("Content-Type") && options.body && typeof options.body === "string") {
      headers.set("Content-Type", "application/json");
    }

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 20000); // 20s timeout

      const response = await fetch(url, {
        ...options,
        headers,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        let detail = `Request failed with status ${response.status}`;
        let parsed: unknown = null;
        try {
          parsed = await response.json();
          if (parsed && typeof parsed === "object") {
            const maybeDetail = (parsed as { detail?: unknown }).detail;
            if (typeof maybeDetail === "string") {
              detail = maybeDetail;
            } else if (Array.isArray(maybeDetail)) {
              // Pydantic validation error array
              detail = maybeDetail
                .map((err) => (typeof err === "object" && err ? (err as { msg?: string }).msg || JSON.stringify(err) : String(err)))
                .join("; ");
            } else if (maybeDetail) {
              detail = JSON.stringify(maybeDetail);
            }
          }
        } catch {
          // Non-JSON error body
          const text = await response.text().catch(() => "");
          if (text) detail = text;
        }

        throw new ApiError(response.status, detail, parsed);
      }

      return (await response.json()) as T;
    } catch (err: unknown) {
      if (err instanceof ApiError) throw err;
      if (err instanceof Error && err.name === "AbortError") {
        throw new ApiError(408, "Request timed out after 20 seconds");
      }
      const message = err instanceof Error ? err.message : "Network error";
      throw new ApiError(0, `Network failure connecting to ${this.baseUrl}: ${message}`);
    }
  }

  // ── Operations ─────────────────────────────────────────────────────────────

  async health(): Promise<{ status: string }> {
    return this.request<{ status: string }>("/health");
  }

  async listCases(): Promise<FraudCase[]> {
    return this.request<FraudCase[]>("/api/cases");
  }

  async getCase(caseId: string): Promise<FraudCase> {
    return this.request<FraudCase>(`/api/cases/${encodeURIComponent(caseId)}`);
  }

  async createCase(caseData: FraudCase): Promise<FraudCase> {
    return this.request<FraudCase>("/api/cases", {
      method: "POST",
      body: JSON.stringify(caseData),
    });
  }

  async getTimeline(caseId: string): Promise<TransactionEvent[]> {
    return this.request<TransactionEvent[]>(
      `/api/cases/${encodeURIComponent(caseId)}/timeline`
    );
  }

  async getGraph(caseId: string): Promise<GraphManifest> {
    return this.request<GraphManifest>(
      `/api/cases/${encodeURIComponent(caseId)}/graph`
    );
  }

  async ingestEvent(
    event: TransactionEvent,
    caseId: string
  ): Promise<TransactionEvent> {
    return this.request<TransactionEvent>(
      `/api/events?case_id=${encodeURIComponent(caseId)}`,
      {
        method: "POST",
        body: JSON.stringify(event),
      }
    );
  }

  async ingestBatch(
    events: TransactionEvent[],
    caseId: string
  ): Promise<{ accepted: number; event_ids: string[] }> {
    return this.request<{ accepted: number; event_ids: string[] }>(
      `/api/events/batch?case_id=${encodeURIComponent(caseId)}`,
      {
        method: "POST",
        body: JSON.stringify(events),
      }
    );
  }

  async analyzeCase(
    caseId: string,
    payload: InvestigationAnalysisRequest
  ): Promise<InvestigationAnalysisResponse> {
    return this.request<InvestigationAnalysisResponse>(
      `/api/cases/${encodeURIComponent(caseId)}/analyze`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  }
}

export const apiClient = new ApiClient();
