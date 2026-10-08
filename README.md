# AEGIS-Flow

> **Temporal Fraud-Flow Intervention Engine**
> Hackathon Prototype — Synthetic Data Only

---

## Problem Statement

Modern financial fraud increasingly operates across multi-hop transaction chains: illicit funds are laundered through a sequence of accounts, often spanning multiple institutions, before reaching a cash-out point. Existing rule-based fraud systems are account-centric and flag individual suspicious transactions in isolation. They cannot reconstruct the full temporal flow of tainted capital, identify the structural chokepoints where intervention would maximally recover illicit funds, or simulate the downstream consequences of blocking a specific transaction. This leaves investigators with fragmented evidence, no provenance chain, and no principled basis for deciding *where* and *when* to intervene in a live fraud flow.

## Solution Overview

AEGIS-Flow reconstructs the full directed temporal transaction graph from normalized synthetic evidence, propagates taint deterministically using a provenance-aware flow-conservation model, predicts likely next hops using a lightweight ML model trained on graph features, and identifies optimal intervention chokepoints using counterfactual simulation. For any candidate intervention, the system computes the expected recovery of illicit capital versus the collateral disruption to legitimate capital, returning a ranked intervention recommendation with a full structured audit trail. An optional LLM layer can translate the structured evidence into a natural-language case summary for investigators, but all provenance decisions, taint values, and intervention rankings are produced entirely by deterministic or learned algorithms — the LLM does not influence any financial conclusion.

---

## Five Core Technical Pillars

| # | Pillar | Description |
|---|--------|-------------|
| 1 | **Temporal Graph Construction** | Transactions are ingested, normalized, and assembled into a time-ordered directed multigraph. Edge weights encode transfer amounts; node attributes carry account metadata and cold-start risk scores. |
| 2 | **Dynamic Taint & Provenance Tracking** | A deterministic, flow-conservation-based taint propagation algorithm tracks the fraction of illicit capital at each node across time. Full provenance lineage (which source taint reached which destination, via which path) is recorded and is reproducible. |
| 3 | **Cold-Start Risk Scoring** | Newly created or data-sparse accounts receive a risk score from a lightweight ML model (gradient-boosted trees) trained on structural graph features and behavioral signals, preventing blind spots in the taint graph. |
| 4 | **Next-Hop Prediction** | A trained ML model estimates the probability distribution over likely next transaction destinations from any active node, enabling proactive identification of probable future hops before they occur. |
| 5 | **Counterfactual Intervention Optimization** | For each candidate chokepoint, the system simulates the counterfactual world where that intervention was applied, computing recoverable illicit capital and collateral impact on legitimate flows. Interventions are ranked by a configurable utility function. |

---

## High-Level Architecture

```
Synthetic Data Layer
        │
        ▼
  Data Ingestion & Normalization
  (bank-agnostic schema, timestamps, amounts, account IDs)
        │
        ▼
  Temporal Graph Engine  ──────────────────────────────────┐
  (directed multigraph, time-ordered edges)                │
        │                                                   │
        ▼                                                   │
  Taint Propagation Engine                         Graph Compression
  (deterministic, flow-conservation)               (summary subgraphs)
        │
        ▼
  ML Layer
  ├── Cold-Start Risk Model (GBT)
  └── Next-Hop Prediction Model (GNN / GBT)
        │
        ▼
  Intervention Engine
  (chokepoint identification + counterfactual simulation)
        │
        ▼
  Structured Evidence Package
  (audit trail, provenance chain, ranked interventions)
        │
        ▼ (optional)
  LLM Explanation Layer
  (natural-language summary only — no financial decisions)
        │
        ▼
  REST API / CLI
        │
        ▼
  Frontend Dashboard
  (graph visualization, intervention explorer)
```

---

## Technology Stack (Initial)

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| Graph Engine | NetworkX (prototype); igraph (scale) |
| ML / Gradient Boosting | scikit-learn, XGBoost |
| Graph Neural Networks | PyTorch Geometric (next-hop model) |
| Data / Serialization | pandas, pyarrow, JSON |
| Backend API | FastAPI |
| Frontend | React + D3.js |
| Configuration | python-dotenv |
| Testing | pytest |
| Synthetic Data Generation | Custom scripts (Faker + controlled topology) |
| LLM Integration (optional) | Google Gemini API (explanation only) |

---

## Repository Structure

```
aegis-flow/
├── backend/        # FastAPI application, graph engine, taint engine, ML models, API routes
├── frontend/       # React dashboard, D3 graph visualizer, intervention explorer
├── data/           # Synthetic datasets, schemas, benchmark fixtures
├── docs/           # Architecture notes, algorithm specs, design decisions
├── scripts/        # Data generation, benchmark runners, utility scripts
├── tests/          # Unit and integration tests
├── .env.example    # Environment variable template
└── README.md       # This file
```

---

## ⚠️ Prototype Disclaimer

**AEGIS-Flow is a research prototype built for a hackathon.**

- It operates **exclusively on synthetic, generated data**. It does not connect to, integrate with, or control any real bank account, payment system, or financial institution.
- It does **not** claim integration with NPCI, RBI, DPIP, or any bank's internal systems.
- It does **not** issue freeze orders, block transactions, or take any action in a live financial network.
- Any similarity to real account numbers, institutions, or transactions in the synthetic data is coincidental.
- Comparative superiority over existing production fraud systems (e.g., AML platforms, real-time fraud engines) **will be evaluated using our benchmark suite** once implemented. No such claim is made at this stage.

---

## License

[MIT](LICENSE)
