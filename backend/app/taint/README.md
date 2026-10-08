# Dynamic Money Provenance model

`TaintEngine` is a deterministic simulation over a `TemporalGraph`. It is not
a legal attribution, a bank-ledger reconstruction, or an account-freezing
decision.

## Model assumptions

- Taint starts only from explicit `TaintSeed(case_id, transaction_id, amount)` inputs.
  The seed transaction's receiver receives that modeled taint. No account is
  inferred tainted from `ScenarioTruth`, graph topology, or ML labels.
- Only `TemporalGraph` active (`completed`) events participate. Events are
  processed in its chronological index order; equal timestamps retain that
  deterministic index order.
- An account has a pooled observable balance: clean capital plus a separate
  integer balance for each seed. Outbound covered funds are allocated in that
  same proportion. Rounding uses integer largest remainders with lexical source
  ID tie-breaking.
- A non-seed inflow is modeled as non-tainted unless its sender's tracked pool
  carries taint. This represents only the observed transaction, never an
  inferred opening balance.
- When outgoing volume exceeds the sender's tracked observable balance, the
  difference is reported as an `ObservableBalanceShortfall`. It adds no taint.
  The recipient still has an observed transaction receipt; that shortfall
  portion is recorded as `unattributed_amount_minor_units`, not silently
  claimed to be source-attributed.
- The engine preserves taint stock: per source, injected taint equals currently
  modeled taint plus modeled termination (zero in this version). Cumulative
  tainted edge volume is a separate movement metric and can exceed initial
  taint after multiple hops.

## Complexity and downstream use

The engine makes one pass over active chronological edges. Per edge allocation
cost is `O(S log S)` for the `S` provenance sources currently pooled at the
sender; no graph traversal is repeated per edge. `TaintResult` exposes current
tainted accounts, edge allocations, per-source traces, balance shortfalls, and
conservation reports for a future counterfactual simulator.
