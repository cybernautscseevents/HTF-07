# Forecast-Aware Counterfactual Interdiction

## 1. Why Observed-Only Counterfactuals Are Insufficient

In real-world anti-financial crime operations, counterfactual simulation evaluated solely against *observed historical transactions* suffers from fundamental oracle leakage and operational lag:

1. **Retrospective Oracle Bias:** An observed-world simulator evaluates interventions against transactions that already occurred. In live production at decision timestamp $T$, the fraudster's future transactions have not yet arrived. Replaying only observed future transactions assumes perfect post-hoc visibility that an investigator does not possess.
2. **Pre-Emptive Interdiction Deficit:** Waiting for downstream transactions to register before intervening allows illicit capital to traverse intermediary mule hops, cross institutional boundaries, or reach irreversible exfiltration endpoints (e.g. cashout, crypto ramps).
3. **Fragility to Route Diversion:** An intervention optimized only for the single observed trajectory may completely fail if the fraudster branches into alternate mule accounts or splits flow across multiple rails.

Forecast-Aware Counterfactual Interdiction elevates AEGIS-Flow from retrospective audit to live, pre-emptive interdiction across plausible future trajectories.

---

## 2. Plausible Future World Generation via Next-Hop Prediction

At prediction timestamp $T$, the system queries the trained `NextHopPredictor` using **strictly causal information** available at or before $T$:

```
Observed State <= T
        ↓
Next-Hop Prediction
        ↓
Top-K Plausible Future Paths (Beam Search)
        ↓
Future World Generation (In-Memory TemporalGraph + Baseline Taint)
        ↓
Existing CounterfactualSimulator Evaluation
        ↓
Robust Intervention Selection
```

1. **Strict Temporal Boundary:** Zero transactions with `occurred_at > T` are accessed.
2. **Candidate Affinity & Softmax:** Pairwise topology and behavioral signals (e.g., shared counterparties, forwarding capacity, degree distribution) produce normalized destination probabilities over active account pools.
3. **Simulation-Only In-Memory Worlds:** For each generated path, an isolated in-memory `TemporalGraph` is provisioned containing observed events $\le T$ augmented with future forecast edges occurring at $T + \Delta t, T + 2\Delta t, \dots$.
4. **Baseline Taint Replay:** `TaintEngine` is re-executed on each future world to establish consistent, baseline taint allocations before counterfactual intervention testing.

---

## 3. Bounded Future Search via Deterministic Beam Search

Unconstrained trajectory generation suffers from combinatorial explosion ($O(K^H)$ paths for branching factor $K$ and horizon $H$). To guarantee strict sub-second decision latency and deterministic execution, AEGIS-Flow employs bounded beam search:

* **Configurable Parameters:**
  - `top_k`: Maximum number of paths retained in the beam at each hop level (default 3).
  - `max_depth`: Maximum forecast horizon in hops (default 3).
  - `min_probability`: Probability cutoff below which candidate branches are pruned (default 0.01).
* **Deterministic Tie-Breaking:** Ties between candidates or paths are broken lexicographically by `account_id` and sequence tuple, eliminating any random sampling or platform non-determinism.
* **Cycle Prevention:** Simple-path constraints prohibit revisiting accounts already traversed in the path, preventing cyclic loops.
* **Early Termination:** If an account lacks candidate counterparties or all candidates fall below the probability threshold, the trajectory terminates naturally without synthetic fabrication.

---

## 4. Probability-Weighted and Worst-Case Robust Outcomes

For each candidate intervention $c$ and each future world $s \in \{1, \dots, M\}$ with normalized probability weight $w_s$ ($\sum_s w_s = 1.0$), the existing `CounterfactualSimulator` evaluates the intervention independently:

$$\mathbb{E}[I] = \sum_{s=1}^M w_s \cdot I_s \quad (\text{Expected Illicit Interception})$$

$$\mathbb{E}[L] = \sum_{s=1}^M w_s \cdot L_s \quad (\text{Expected Legitimate Collateral})$$

$$\text{Worst-Case Recovery} = \min_{s} I_s$$

$$\text{Worst-Case Collateral} = \max_{s} L_s$$

$$\text{Intervention Stability} = \sum_{s=1}^M w_s \cdot \mathbb{I}(I_s > 0)$$

### Robust Intervention Selection Policy

When selecting among Pareto-efficient candidates across plausible futures, the optimizer applies a deterministic 5-stage ranking:
1. **Feasibility Compliance:** Strict adherence to `OptimizationConstraints` across futures.
2. **Probability-Weighted Recovery:** Maximize expected illicit interception $\mathbb{E}[I]$.
3. **Worst-Case Collateral Protection:** Minimize maximum legitimate disruption $\max_s L_s$.
4. **Guaranteed Minimum Recovery:** Maximize worst-case illicit interception $\min_s I_s$.
5. **Deterministic Tie-Breaking:** Minimize scope (affected accounts and edges), followed by stable candidate sort keys.

---

## 5. Explicit Separation: Observed vs. Forecast Events

Forecast events are fundamentally predictive hypotheses, not financial settlement truth:

| Dimension | Observed Event (`TransactionEvent`) | Forecast Event (`ForecastTransactionEvent`) |
| :--- | :--- | :--- |
| **Origin** | `BANK_FEED`, `API_PUSH`, `MANUAL_UPLOAD` | `SYNTHETIC` |
| **Persistence** | Canonical database, audit ledger | In-memory simulation only, NEVER persisted |
| **Identity** | Bank UTR / canonical event ID | Prefixed `fc-evt-{path_id}-{hop}` |
| **Semantics** | Established historical legal fact | Counterfactual predictive scenario |
| **Downstream Impact** | Triggers regulatory filing & ledger debits | Triggers simulation scoring only |

This separation ensures that no machine learning prediction is ever mistaken for a booked banking transaction.

---

## 6. Limitations of Predicted Future Transaction Amounts

1. **Conservation Assumption:** The current MVP models 100% pass-through of the sender's modeled forwardable tainted balance (in integer paise), bounded by available modeled balance.
2. **Lack of Dynamic Structuring:** Complex real-time fee splits, micro-structuring below AML thresholds, or external off-ledger deposits cannot be perfectly predicted without explicit fraudster behavior models.
3. **Non-Settlement Nature:** Amounts represent simulation flow hypotheses to stress-test candidate holds, not real-time banking settlement guarantees.

---

## 7. Future Horizon: Adversarial Fraudster Simulation

The modularity of `ForecastPathGenerator` and `ForecastAwareCounterfactualEvaluator` establishes the foundation for adversarial game-theoretic simulation:

* **Dynamic Counter-Intervention Re-Routing:** If a fraudster observes an account hold on mule $M_1$, an adversarial policy model can dynamically re-route remaining funds through alternative mule networks ($M_2, M_3$).
* **Minimax / Stackelberg Formulations:** Formulating interdiction as a bilevel optimization game where the bank chooses holds to maximize worst-case recovery against an adaptive adversary minimizing interception.
* **Reinforcement Learning Agent Integration:** Simulating adversarial policies trained via multi-agent reinforcement learning directly against AEGIS-Flow counterfactual defenses.
