# AEGIS-Flow — Investigator Command Center Frontend

Interactive investigator dashboard and command center for **AEGIS-Flow** (Temporal Fraud-Flow Intervention Engine).

Built as an enterprise-grade financial investigation workspace connecting directly to the FastAPI analysis pipeline (`POST /api/cases/{case_id}/analyze`, graph, timeline, and event ingestion endpoints).

---

## Tech Stack

- **Next.js**: 16.4.0 (App Router, Turbopack)
- **React**: 19.3.0
- **TypeScript**: 5.9.3 (Strict mode, zero un-typed API layers)
- **Styling**: Tailwind CSS 4 (Curated slate/emerald/amber/rose/cyan palette, dark high-contrast command center)
- **Graph Engine**: Cytoscape.js 3.34 with Directed Breadthfirst & Compound Spring Embedder (cose) physics
- **Icons**: Lucide React
- **Test Runner**: Node.js Native Test Runner (`node --test --experimental-strip-types`)

---

## Environment Configuration

The frontend connects to the AEGIS-Flow FastAPI backend via `NEXT_PUBLIC_API_BASE_URL`.

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Base URL of the running FastAPI server |

A template is provided in `frontend/.env.example`:
```bash
cp frontend/.env.example frontend/.env.local
```

---

## Quickstart

### 1. Start the AEGIS-Flow Backend
From the repository root:
```bash
# Using the virtual environment
.venv\Scripts\uvicorn backend.app.main:app --reload --port 8000
```
Backend health check is accessible at `http://localhost:8000/health`.

### 2. Start the Frontend Application
From the `frontend/` directory:
```bash
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## Verification & Testing

From the `frontend/` directory:

- **Run Test Suite**: `npm test` (Runs 21 unit tests covering currency minor units, error serialization, demo idempotency, graph mapping, and stage handling)
- **Type Check**: `npx tsc --noEmit`
- **Lint**: `npm run lint`
- **Production Build**: `npm run build`

---

## Investigation Workflow & Features

### 1. Deterministic Demo Case ("Operation ShatterFlow")
Click **"Load Demo Case"** in the top navigation bar to initialize a deterministic synthetic fraud case (`case-demo-synthetic-001`):
- **Victim Account**: `Victim-Corp-99`
- **Initial Fraud Transaction**: ₹5,00,000 (50,000,000 paise) seeded to mule layer Alpha (`Mule-Alpha-101`).
- **Layer 2 Splitting**: Funds branch to Beta (`Mule-Beta-202`) and Gamma (`Mule-Gamma-303`).
- **Clean Commingling**: Legitimate funds (₹1,00,000) enter Beta from merchant `Clean-Merchant-505`.
- **Layer 3 Consolidation**: Funds aggregate at Delta (`Mule-Delta-404`).
- **Exit Mule**: Funds attempt escape via off-ramp `Exit-CryptoDesk-909`.
- **Safe & Idempotent**: Uses existing `/api/cases` and `/api/events/batch` APIs with conflict handling.

### 2. Temporal Exploration Scrubber (Decision Time $T$)
- Investigators can scrub backward or forward across observation time.
- **Observed at $T$**: Solid green edges for transactions verified prior to or at decision time $T$.
- **Later Observations**: Dimmed yellow edges for transactions discovered after $T$, preventing lookahead bias.
- **Stale Analysis Detection**: Scrubbing $T$ marks the current analysis as *Stale*, prompting the investigator to re-run the pipeline with explicit temporal constraints.

### 3. Interactive Cytoscape Transaction Graph
- Directed financial flow with edge widths scaled to transfer amounts.
- **Node Classification**: Victim (blue), Fraud Seed (amber), Tainted Mules (red/rose), and Exit Accounts (purple).
- **Edge Distinctions**:
  - Historical confirmed transactions: Solid arrows.
  - Future unconfirmed observations: Dimmed yellow lines.
  - Forecasted trajectory edges: Dashed cyan arrows with labeled probabilities ($P$).
  - Min-cut barrier edges: Highlighted orange edges with shield markers.
- **Entity Inspector**: Clicking any node or edge opens a forensic inspector drawer showing exact paise values, timestamps, and model predictions.
- **Layout Reset**: Toggle between hierarchical Tree (`breadthfirst`) and organic Spring-embedder (`cose`) layouts.

### 4. Money Provenance & Taint Conservation
- Strict FIFO taint conservation tracking through intermediary accounts.
- Displays initial taint seed, tainted balance per account, clean balances, and downstream taint.
- All currency values formatted cleanly while preserving integer minor units (paise) at the domain layer.
- Clear legal caveat: *Modeled provenance represents analytical simulations, not forensic proof of legal guilt.*

### 5. ML Intelligence & Trajectory Forecasting
- Account-level mule risk scores from LightGBM with model versioning.
- Next-hop transition probability distribution from seed accounts.
- Monte Carlo multi-step forecast paths with path probabilities.
- Plain-language explanation that next-hop prediction models plausible egress, not confirmed settlement.

### 6. Temporal Min-Cut Barrier & Intervention Optimizer
- Calculates minimum-capacity temporal edge cut disconnecting source from exit sink.
- Clearly distinguishes a **complete multi-edge cut set** (which disconnects all modeled routes) from **single edge-hold candidates** (which only delay or divert flow).
- Multi-objective Pareto optimization balancing **modeled illicit capital intercepted** against **legitimate capital affected (collateral damage)**.
- Robustness metrics comparing expected vs. worst-case outcomes under uncertainty.

---

## Architectural Principles & Boundaries

1. **Strict Separation of Concerns**: The frontend is purely a visualization, exploration, and human-in-the-loop decision-support layer. Zero business or optimization logic is duplicated in TypeScript.
2. **Canonical Contracts Preserved**: The frontend never alters or extends canonical financial contracts in `contracts/`.
3. **No Fabricated Data**: When an API returns a partial analysis, missing model stage, or error, the UI displays explicit diagnostic badges ("Unavailable", "Insufficient Evidence", "Failed") rather than invented metrics or fake confidence percentages.
4. **No Real Freezes Dispatched**: Actions provide decision recommendations with explanations, explicitly stating that legal authorization and banking holds must be executed through separate compliance channels.
