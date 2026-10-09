export type CaseOrigin =
  | "customer_report"
  | "bank_detection"
  | "intelligence_feed"
  | "law_enforcement"
  | "synthetic";

export type CaseStatus =
  | "open"
  | "under_investigation"
  | "escalated"
  | "closed_recovered"
  | "closed_unrecovered";

export interface FraudCase {
  schema_version: string;
  case_id: string;
  title: string;
  description: string | null;
  origin: CaseOrigin;
  status: CaseStatus;
  transaction_ids: string[];
  opened_at: string;
  updated_at: string;
}
