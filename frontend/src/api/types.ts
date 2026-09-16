/**
 * API response types.
 *
 * Mirrors the backend Pydantic models. Kept hand-written rather than generated
 * from the OpenAPI schema: the surface is small, and a generated client would
 * add a build step and a large dependency for types that change rarely.
 */

export type UserRole = "admin" | "auditor" | "reviewer" | "viewer";
export type FlagSeverity = "info" | "low" | "medium" | "high" | "critical";
export type FlagStatus = "open" | "acknowledged" | "resolved" | "dismissed";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  organization_id: string;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  created_at: string;
}

export interface Tokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface RegisterResponse {
  user: User;
  organization: Organization;
  tokens: Tokens;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Company {
  id: string;
  name: string;
  cik: string | null;
  ticker: string | null;
  sector: string | null;
  sic_code: string | null;
  country: string | null;
  is_public_reference: boolean;
}

export interface StatementSummary {
  id: string;
  company_id: string;
  company_name: string | null;
  fiscal_year: number;
  fiscal_period: string;
  filing_type: string;
  period_end_date: string | null;
  filed_date: string | null;
  risk_score: number | null;
  source_dataset: string;
}

export interface LineItem {
  id: string;
  tag: string;
  label: string | null;
  /** Serialised as a string: these are exact decimals that a JS number cannot
   *  hold without rounding. Never parse one with parseFloat for display. */
  value: string;
  unit: string;
  statement_section: string;
}

export interface AuditFlag {
  id: string;
  statement_id: string;
  flag_type: string;
  severity: FlagSeverity;
  status: FlagStatus;
  detection_method: string;
  score: number | null;
  description: string;
  detail: Record<string, unknown>;
  explanation: string | null;
  created_at: string;
}

/** Every ratio is nullable: null means "not computable", never zero. */
export interface RatioSet {
  current_ratio: number | null;
  quick_ratio: number | null;
  debt_to_equity: number | null;
  gross_margin: number | null;
  net_margin: number | null;
  operating_margin: number | null;
  return_on_assets: number | null;
  asset_turnover: number | null;
  accruals_ratio: number | null;
}

export interface StatementDetail extends StatementSummary {
  line_items: LineItem[];
  flags: AuditFlag[];
  ratios: RatioSet;
  is_fraud_label: boolean | null;
}

export interface DashboardSummary {
  total_statements: number;
  open_flags: number;
  critical_flags: number;
  high_risk_statements: number;
  average_risk_score: number | null;
}

export interface DocumentRecord {
  id: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  doc_type: string;
  status: string;
  chunk_count: number;
  created_at: string;
}

export interface SearchResult {
  chunk_id: string;
  document_id: string;
  document_name: string;
  chunk_index: number;
  text: string;
  /** Cosine similarity, 0 to 1. Higher is a closer match. */
  similarity: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  count: number;
}

export interface AskSource {
  index: number;
  document_id: string;
  document_name: string;
  similarity: number;
  excerpt: string;
}

export interface AskResponse {
  question: string;
  answer: string;
  citations: number[];
  /** False when retrieval found nothing that supports an answer. */
  sufficient_context: boolean;
  sources: AskSource[];
  cached: boolean;
}

export interface ReportSummary {
  id: string;
  statement_id: string;
  title: string;
  status: string;
  risk_score: number | null;
  created_at: string;
  generated_at: string | null;
}

export interface ReportDetail extends ReportSummary {
  content: Record<string, unknown>;
  narrative_available: boolean;
  error: string | null;
}

export interface ExportFormats {
  html: boolean;
  pdf: boolean;
  pdf_unavailable_reason: string | null;
}

export interface LLMBudget {
  calls_today: number;
  ceiling: number;
  remaining: number;
  exhausted: boolean;
  providers_configured: boolean;
}
