import type {
  FraudCase,
  TransactionEvent,
  InvestigationAnalysisRequest,
} from "../../types/index.ts";
import { ApiClient } from "../api/client.ts";

export const DEMO_CASE_ID = "case-demo-synthetic-001";
export const DEMO_BASE_TIME = "2026-10-09T08:00:00Z";

export const DEMO_CASE: FraudCase = {
  schema_version: "1.0.0",
  case_id: DEMO_CASE_ID,
  title: "Operation ShatterFlow — Multi-Branch Funnel & Exit",
  description:
    "Deterministic synthetic scenario: ₹5,00,000 UPI corporate fraud seed injected into Alpha mule, split across Beta and Gamma intermediaries with legitimate merchant commingling, funneled to Delta accumulator and routed to CryptoDesk exit sink.",
  origin: "synthetic",
  status: "open",
  transaction_ids: [
    "tx-seed-1001",
    "tx-split-1002",
    "tx-split-1003",
    "tx-clean-1004",
    "tx-hop-1005",
    "tx-hop-1006",
    "tx-exit-1007",
  ],
  opened_at: DEMO_BASE_TIME,
  updated_at: DEMO_BASE_TIME,
};

export const DEMO_EVENTS: TransactionEvent[] = [
  {
    schema_version: "1.0.0",
    event_id: "ev-demo-001",
    transaction_id: "tx-seed-1001",
    reference: "UPI/DEMO/SEED/001",
    sender: { account_id: "Victim-Corp-99", institution: "HDFC" },
    receiver: { account_id: "Mule-Alpha-101", institution: "ICICI" },
    amount_minor_units: 50_000_000, // ₹5,00,000
    currency: "INR",
    occurred_at: "2026-10-09T08:00:00Z",
    observed_at: "2026-10-09T08:00:05Z",
    status: "completed",
    channel: "upi",
    origin: "synthetic",
  },
  {
    schema_version: "1.0.0",
    event_id: "ev-demo-002",
    transaction_id: "tx-split-1002",
    reference: "UPI/DEMO/SPLIT/002",
    sender: { account_id: "Mule-Alpha-101", institution: "ICICI" },
    receiver: { account_id: "Mule-Beta-202", institution: "AXIS" },
    amount_minor_units: 30_000_000, // ₹3,00,000 (Branch A)
    currency: "INR",
    occurred_at: "2026-10-09T08:15:00Z",
    observed_at: "2026-10-09T08:15:04Z",
    status: "completed",
    channel: "upi",
    origin: "synthetic",
  },
  {
    schema_version: "1.0.0",
    event_id: "ev-demo-003",
    transaction_id: "tx-split-1003",
    reference: "UPI/DEMO/SPLIT/003",
    sender: { account_id: "Mule-Alpha-101", institution: "ICICI" },
    receiver: { account_id: "Mule-Gamma-303", institution: "KOTAK" },
    amount_minor_units: 20_000_000, // ₹2,00,000 (Branch B)
    currency: "INR",
    occurred_at: "2026-10-09T08:20:00Z",
    observed_at: "2026-10-09T08:20:05Z",
    status: "completed",
    channel: "upi",
    origin: "synthetic",
  },
  {
    schema_version: "1.0.0",
    event_id: "ev-demo-004",
    transaction_id: "tx-clean-1004",
    reference: "IMPS/DEMO/CLEAN/004",
    sender: { account_id: "Clean-Merchant-505", institution: "SBI" },
    receiver: { account_id: "Mule-Beta-202", institution: "AXIS" },
    amount_minor_units: 10_000_000, // ₹1,00,000 (Clean commingling)
    currency: "INR",
    occurred_at: "2026-10-09T08:35:00Z",
    observed_at: "2026-10-09T08:35:03Z",
    status: "completed",
    channel: "imps",
    origin: "synthetic",
  },
  {
    schema_version: "1.0.0",
    event_id: "ev-demo-005",
    transaction_id: "tx-hop-1005",
    reference: "UPI/DEMO/HOP/005",
    sender: { account_id: "Mule-Gamma-303", institution: "KOTAK" },
    receiver: { account_id: "Mule-Delta-404", institution: "YES" },
    amount_minor_units: 20_000_000, // ₹2,00,000
    currency: "INR",
    occurred_at: "2026-10-09T08:50:00Z",
    observed_at: "2026-10-09T08:50:06Z",
    status: "completed",
    channel: "upi",
    origin: "synthetic",
  },
  {
    schema_version: "1.0.0",
    event_id: "ev-demo-006",
    transaction_id: "tx-hop-1006",
    reference: "UPI/DEMO/HOP/006",
    sender: { account_id: "Mule-Beta-202", institution: "AXIS" },
    receiver: { account_id: "Mule-Delta-404", institution: "YES" },
    amount_minor_units: 35_000_000, // ₹3,50,000 (Commingled: ₹3,00,000 tainted + ₹50,000 clean)
    currency: "INR",
    occurred_at: "2026-10-09T09:10:00Z",
    observed_at: "2026-10-09T09:10:04Z",
    status: "completed",
    channel: "upi",
    origin: "synthetic",
  },
  {
    schema_version: "1.0.0",
    event_id: "ev-demo-007",
    transaction_id: "tx-exit-1007",
    reference: "NEFT/DEMO/EXIT/007",
    sender: { account_id: "Mule-Delta-404", institution: "YES" },
    receiver: { account_id: "Exit-CryptoDesk-909", institution: "INDUSIND" },
    amount_minor_units: 50_000_000, // ₹5,00,000 (Exit cash-out)
    currency: "INR",
    occurred_at: "2026-10-09T09:40:00Z",
    observed_at: "2026-10-09T09:40:08Z",
    status: "completed",
    channel: "neft",
    origin: "synthetic",
  },
];

export const DEMO_DEFAULT_DECISION_TIME = "2026-10-09T08:30:00Z";

export function getDemoAnalysisRequest(
  decisionTimestamp: string = DEMO_DEFAULT_DECISION_TIME
): InvestigationAnalysisRequest {
  return {
    simulation_timestamp: decisionTimestamp,
    taint_seeds: [
      {
        transaction_id: "tx-seed-1001",
        tainted_amount_minor_units: 50_000_000,
      },
    ],
    source_account_ids: ["Mule-Alpha-101"],
    sink_account_ids: ["Exit-CryptoDesk-909"],
    forecast_config: {
      top_k: 3,
      max_depth: 3,
      hop_delay_seconds: 300,
    },
    constraints: {
      minimum_required_illicit_recovery: 0,
      maximum_interventions: 2,
    },
  };
}

/**
 * Safely loads the deterministic demo scenario into the AEGIS-Flow backend.
 * Avoids duplicate errors by verifying existence first.
 */
export async function loadDemoScenario(
  client: ApiClient
): Promise<{ case: FraudCase; eventsCount: number }> {
  let existingCase: FraudCase | null = null;
  try {
    existingCase = await client.getCase(DEMO_CASE_ID);
  } catch {
    existingCase = null;
  }

  if (!existingCase) {
    existingCase = await client.createCase(DEMO_CASE);
    await client.ingestBatch(DEMO_EVENTS, DEMO_CASE_ID);
    return { case: existingCase, eventsCount: DEMO_EVENTS.length };
  }

  // Case already exists: check if events are present
  const timeline = await client.getTimeline(DEMO_CASE_ID).catch(() => []);
  if (timeline.length === 0) {
    await client.ingestBatch(DEMO_EVENTS, DEMO_CASE_ID);
    return { case: existingCase, eventsCount: DEMO_EVENTS.length };
  }

  return { case: existingCase, eventsCount: timeline.length };
}
