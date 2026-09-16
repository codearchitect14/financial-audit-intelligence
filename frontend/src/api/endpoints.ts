/**
 * Typed wrappers for each API endpoint.
 *
 * One function per endpoint, so a URL or parameter name appears exactly once
 * in the codebase and a backend change is a single-file edit here.
 */

import { api, queryString } from "./client";
import type {
  AskResponse,
  AuditFlag,
  Company,
  DashboardSummary,
  DocumentRecord,
  ExportFormats,
  FlagStatus,
  LLMBudget,
  Page,
  RegisterResponse,
  ReportDetail,
  ReportSummary,
  SearchResponse,
  StatementDetail,
  StatementSummary,
  Tokens,
  User,
  UserRole,
} from "./types";

export const auth = {
  register: (payload: {
    email: string;
    password: string;
    full_name: string;
    organization_name: string;
  }) => api.post<RegisterResponse>("/auth/register", payload, { skipAuth: true }),

  login: (payload: { email: string; password: string }) =>
    api.post<Tokens>("/auth/login", payload, { skipAuth: true }),

  logout: (refreshToken: string) =>
    api.post<void>("/auth/logout", { refresh_token: refreshToken }),

  me: () => api.get<User>("/auth/me"),

  setRole: (userId: string, role: UserRole) =>
    api.patch<User>(`/auth/users/${userId}/role`, { role }),
};

export const dashboard = {
  summary: () => api.get<DashboardSummary>("/dashboard"),
};

export const companies = {
  list: (params: { search?: string; sector?: string; limit?: number; offset?: number } = {}) =>
    api.get<Page<Company>>(`/companies${queryString(params)}`),

  get: (id: string) => api.get<Company>(`/companies/${id}`),
};

export const statements = {
  list: (
    params: {
      company_id?: string;
      fiscal_year?: number;
      min_risk_score?: number;
      has_open_flags?: boolean;
      limit?: number;
      offset?: number;
    } = {},
  ) => api.get<Page<StatementSummary>>(`/statements${queryString(params)}`),

  get: (id: string) => api.get<StatementDetail>(`/statements/${id}`),
};

export const flags = {
  list: (
    params: {
      statement_id?: string;
      status?: FlagStatus;
      severity?: string;
      limit?: number;
      offset?: number;
    } = {},
  ) => api.get<Page<AuditFlag>>(`/flags${queryString(params)}`),

  updateStatus: (flagId: string, status: FlagStatus) =>
    api.patch<AuditFlag>(`/flags/${flagId}`, { status }),
};

export const documents = {
  list: (params: { limit?: number; offset?: number } = {}) =>
    api.get<Page<DocumentRecord>>(`/documents${queryString(params)}`),

  get: (id: string) => api.get<DocumentRecord>(`/documents/${id}`),

  upload: (file: File, docType = "other") => {
    const form = new FormData();
    form.append("file", file);
    form.append("doc_type", docType);
    // Content-Type is deliberately not set: the browser has to generate the
    // multipart boundary itself, and setting it by hand breaks the upload.
    return api.post<DocumentRecord>("/documents", form);
  },
};

export const search = {
  query: (params: { q: string; limit?: number; document_id?: string }) =>
    api.get<SearchResponse>(`/search${queryString(params)}`),
};

export const insights = {
  explain: (statementId: string, force = false) =>
    api.post<{ statement_id: string; flags: AuditFlag[]; explained_count: number }>(
      "/explain",
      { statement_id: statementId, force },
    ),

  ask: (question: string, passages = 8) =>
    api.post<AskResponse>("/ask", { question, passages }),

  budget: () => api.get<LLMBudget>("/llm/budget"),
};

export const reports = {
  list: (params: { limit?: number; offset?: number } = {}) =>
    api.get<Page<ReportSummary>>(`/reports${queryString(params)}`),

  get: (id: string) => api.get<ReportDetail>(`/reports/${id}`),

  generate: (statementId: string, includeNarrative = true) =>
    api.post<ReportDetail>("/reports", {
      statement_id: statementId,
      include_narrative: includeNarrative,
    }),

  formats: () => api.get<ExportFormats>("/reports/formats"),

  exportUrl: (id: string, fmt: "html" | "pdf") =>
    `${import.meta.env.VITE_API_BASE_URL ?? ""}/api/v1/reports/${id}/export?fmt=${fmt}`,

  /** Fetch an export as a blob, so the Authorization header is sent.
   *  A plain link cannot carry one and would return 401. */
  exportBlob: async (id: string, fmt: "html" | "pdf"): Promise<Blob> => {
    const response = await api.get<Response>(`/reports/${id}/export?fmt=${fmt}`, {
      raw: true,
    });
    return response.blob();
  },
};

export const health = {
  ready: () =>
    api.get<{ status: string; checks: Record<string, string> }>("/health/ready", {
      skipAuth: true,
    }),
};
