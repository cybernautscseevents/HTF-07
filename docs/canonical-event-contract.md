# Canonical Event Contract — Design Document

> **AEGIS-Flow Step 2** · Schema Version 1.0.0
> Single source-of-truth data models for every AEGIS-Flow component.

---

## 1. Why the Canonical Contract Exists

AEGIS-Flow is a multi-stage pipeline:

```
Fraud Signal → Canonical Event → Temporal Graph → Taint Propagation
→ Feature Extraction → ML → Counterfactual Simulation
→ Intervention Optimization → Evidence + Recommendation → Frontend
```

Every stage consumes and produces financial data. Without a shared,
frozen schema, each subsystem would invent its own representation of
transactions, accounts, cases, and evidence — leading to:

- **Duplication** — three competing `Transaction` definitions in
  backend, ML, and frontend.
- **Drift** — a field renamed in the graph engine but not in the API.
- **Precision loss** — one service uses floats for money, another uses
  decimals, a third uses strings.

The canonical contract eliminates these problems by defining **one set
of Pydantic v2 models** that every component imports directly.

---

## 2. Observed Facts vs. Derived/Computed Data

The contract captures **observed facts only** — data that exists before
any AEGIS-Flow engine processes it:

| Observed (in contract) | Derived (NOT in contract) |
|------------------------|--------------------------|
| Sender account ID | Taint amount |
| Receiver account ID | Risk score |
| Transfer amount | Next-hop probability |
| Event occurrence time | Chokepoint score |
| Event observation time | Intervention recommendation |
| Transaction status | ML prediction confidence |
| Channel (UPI, NEFT…) | Graph centrality |
| Event origin | Counterfactual recovery |
| Case origin/source | |
| Case status | |

Derived fields will be produced by downstream services (taint engine,
ML models, intervention optimizer) and attached via the
`EvidenceEnvelope` or service-specific response types — never baked
into the core event.

---

## 3. Money Representation

### Rule: integer minor units, never floating point.

For **schema version 1.0.0**, INR is the primary/validated currency.
`amount_minor_units` represents **paise** (1 INR = 100 paise).

| Currency | Minor unit | 1 major unit = |
|----------|-----------|---------------|
| INR | paise | 100 paise |

**Example:** ₹50,000.00 → `amount_minor_units = 5_000_000`

**Why?** IEEE-754 floating point cannot represent all decimal fractions
exactly. `0.1 + 0.2 ≠ 0.3` in float arithmetic. Financial systems
must never lose precision, so we use integers throughout the pipeline.

The `currency` field is a 3-letter upper-case ISO-4217 code (e.g.
`"INR"`). It is validated to be exactly 3 characters and upper-case.
The schema structurally accepts any valid 3-letter code, but the
minor-unit semantics (paise = 1/100) are defined for INR only in this
version.

> **Future consideration:** Multi-currency support with explicit
> currency-exponent metadata (e.g. mapping `"INR"` → exponent 2,
> `"JPY"` → exponent 0) may be added in a later schema version.
> The current `amount_minor_units` + `currency` design is forward-
> compatible with this extension.

---

## 4. Timestamp Rules

### Dual timestamps

Each `TransactionEvent` carries two timestamps:

| Field | Meaning |
|-------|---------|
| `occurred_at` | When the financial event **actually happened** |
| `observed_at` | When the event was **received/observed by AEGIS-Flow** |

This separation is important because ingestion delay is real — a bank
feed may deliver events minutes or hours after they occur. Downstream
engines (temporal graph, taint propagation) need the true event time,
while audit/provenance needs the observation time.

### Rules

1. **All timestamps must be timezone-aware.** Naive `datetime` objects
   are rejected by validation.
2. **Canonical serialization uses UTC ISO-8601** (e.g.
   `2026-10-08T14:30:00Z`).
3. **Non-UTC timezones are accepted on input** and their offset is
   preserved in the model. Consumers that need UTC should convert
   explicitly.

**Why?** Financial transactions span multiple time zones. Stripping
timezone information silently creates ambiguity about *when* an event
actually occurred.

---

## 5. Event Identity vs. Transaction Identity

Each `TransactionEvent` carries two identifiers:

| Field | Purpose |
|-------|---------|
| `event_id` | Unique, immutable **observation** identity. Each ingested event gets its own `event_id`. |
| `transaction_id` | Stable **business/payment** identity. Represents the underlying payment in the source system. |

Multiple lifecycle observations of the same payment (e.g. `pending` →
`completed` → `reversed`) share the same `transaction_id` but have
distinct `event_id` values.

> **Note:** This schema defines the identity fields only. Event-stream
> ordering, deduplication, and lifecycle-state-machine logic are
> service-layer concerns and are not implemented in the contract.

---

## 6. Account Identity Rules

- `account_id` is an **opaque string** — it may be a SHA-256 hash, a
  pseudonymized token, or a masked identifier.
- The contract **does not** prescribe its format — only that it is
  non-empty.
- `institution` and `label` are optional metadata.
- The `AccountReference` model uses Pydantic's `frozen=True` to
  prevent top-level attribute reassignment.

**Why opaque?** AEGIS-Flow is a prototype using synthetic data. Real
account numbers are never stored. The opaque design also future-proofs
the schema for privacy-preserving deployments.

---

## 7. Case / Evidence Relationship

### FraudCase

A `FraudCase` groups zero or more transaction IDs under a single
investigation. A case **may be opened before any transaction events
are ingested** — for example, from a customer report, bank detection
signal, or shared intelligence feed.

The `origin` field records how the case entered AEGIS-Flow:

| `CaseOrigin` value | Meaning |
|---------------------|---------|
| `customer_report` | Opened from a victim/customer complaint |
| `bank_detection` | Flagged by an institution's existing fraud system |
| `shared_intelligence` | Received from shared intelligence feeds |
| `manual_investigation` | Created manually by an analyst |
| `synthetic` | Generated by the AEGIS-Flow simulator |

```
FraudCase
  ├── case_id: "case-2026-00042"
  ├── origin: "bank_detection"
  ├── transaction_ids: ["txn-001", "txn-002", ...]  (may be [])
  └── status: "under_review"

EvidenceEnvelope
  ├── evidence_id: "ev-001"
  ├── case_id: "case-2026-00042"   ← links to the case
  ├── provider_type: "graph_engine"
  ├── provider_name: "temporal-graph-builder-v1"
  ├── summary: "..."
  ├── body: { ... }               ← opaque, provider-specific
  └── created_at: "2026-10-08T19:00:00Z"
```

- An **EvidenceEnvelope** is a timestamped artifact produced by any
  AEGIS-Flow subsystem (or a human analyst) and linked to a case via
  `case_id`.
- The `body` dict is intentionally **opaque** — each provider defines
  its own internal schema. The canonical contract validates the
  envelope metadata, not the body contents.
- **Referential integrity** (e.g. verifying that `transaction_ids` in
  a case actually exist, or that `case_id` in evidence refers to a
  real case) is a **service-layer responsibility**, not enforced by the
  contract.

---

## 8. Immutability Model

All canonical models use Pydantic's `frozen=True` configuration.  This
means:

- **Top-level attribute assignment is prevented.**  Attempting to set
  `event.transaction_id = "new-value"` on a constructed model instance
  will raise a `ValidationError`.
- **Nested mutable containers are NOT deeply frozen.**  A `dict` or
  `list` payload (e.g. `EvidenceEnvelope.body` or
  `FraudCase.transaction_ids`) remains a standard Python mutable
  container.  Consumers *can* mutate the contents of these nested
  structures after construction unless they explicitly convert them to
  immutable types (e.g. `tuple`, `frozenset`, or `MappingProxyType`).
- **This contract does not implement deep immutable data structures.**
  Full deep-freeze machinery adds complexity that is not required at
  this stage.  If downstream services need guarantees beyond top-level
  assignment prevention, they should defensively copy or convert nested
  payloads.

---

## 9. Example Event

```json
{
  "schema_version": "1.0.0",
  "event_id": "evt-20261008-00001",
  "transaction_id": "txn-20261008-00001",
  "reference": "UTR-HDFC-928374650012",
  "sender": {
    "account_id": "acct-sha256-a1b2c3d4",
    "institution": "HDFC Bank",
    "label": "Sender A"
  },
  "receiver": {
    "account_id": "acct-sha256-e5f6g7h8",
    "institution": "ICICI Bank",
    "label": "Receiver B"
  },
  "amount_minor_units": 5000000,
  "currency": "INR",
  "occurred_at": "2026-10-08T14:30:00Z",
  "observed_at": "2026-10-08T14:30:02Z",
  "status": "completed",
  "channel": "upi",
  "origin": "bank_feed"
}
```

This represents a ₹50,000.00 UPI transfer from an HDFC account to an
ICICI account, observed from a bank feed.  The event occurred at
14:30:00 UTC and was ingested by AEGIS-Flow 2 seconds later.

---

## 10. Fields Intentionally Excluded (Computed Later)

The following fields are **deliberately absent** from the canonical
contract because they are produced by downstream AEGIS-Flow engines:

| Field | Produced by | Why excluded |
|-------|------------|--------------|
| `taint_amount` | Taint Propagation Engine | Derived from flow-conservation algorithm |
| `taint_fraction` | Taint Propagation Engine | Ratio of illicit to total flow at a node |
| `risk_score` | Cold-Start Risk Model (ML) | ML prediction, not observed data |
| `next_hop_probability` | Next-Hop Prediction Model | ML prediction |
| `chokepoint_score` | Intervention Engine | Graph-structural metric |
| `intervention_rank` | Intervention Engine | Optimization output |
| `counterfactual_recovery` | Counterfactual Simulator | Simulation output |
| `model_confidence` | Any ML model | Prediction metadata |
| `graph_centrality` | Graph Engine | Structural computation |
| `llm_summary` | LLM Explanation Layer | Generated text |

These values will be attached to cases via `EvidenceEnvelope` objects
or returned in service-specific API response models. They are never
part of the raw event.

---

## Schema Summary

| Model | Module | Key fields |
|-------|--------|-----------|
| `AccountReference` | `contracts.account` | `account_id`, `institution?`, `label?` |
| `TransactionEvent` | `contracts.transaction` | `event_id`, `transaction_id`, `sender`, `receiver`, `amount_minor_units`, `currency`, `occurred_at`, `observed_at`, `status`, `channel`, `origin` |
| `FraudCase` | `contracts.case` | `case_id`, `title`, `origin`, `status`, `transaction_ids` (default `[]`), `opened_at`, `updated_at` |
| `EvidenceEnvelope` | `contracts.evidence` | `evidence_id`, `case_id`, `provider_type`, `provider_name`, `summary`, `body`, `created_at` |

| Enum | Module | Values |
|------|--------|--------|
| `TransactionStatus` | `contracts.enums` | `pending`, `completed`, `failed`, `reversed`, `held` |
| `TransactionChannel` | `contracts.enums` | `upi`, `neft`, `rtgs`, `imps`, `wire`, `card`, `cash`, `internal`, `other` |
| `EventOrigin` | `contracts.enums` | `bank_feed`, `manual_upload`, `api_push`, `synthetic` |
| `CaseStatus` | `contracts.enums` | `open`, `under_review`, `escalated`, `resolved`, `closed` |
| `CaseOrigin` | `contracts.enums` | `customer_report`, `bank_detection`, `shared_intelligence`, `manual_investigation`, `synthetic` |
| `EvidenceProviderType` | `contracts.enums` | `ingestion`, `graph_engine`, `taint_engine`, `ml_model`, `human_analyst`, `external_system` |
