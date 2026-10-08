# AEGIS-Flow Evaluation & Benchmark

This benchmark compares the existing `MultiObjectiveInterventionOptimizer`
with four deterministic strategies on the ten synthetic scenario families.
Every strategy receives the same graph, taint result, candidate tuple,
simulation timestamp, and `OptimizationConstraints`. The counterfactual
simulator evaluates the common candidate set once; selectors cannot request
additional candidates.

## Strategies and information available

* **Highest Risk** uses only an account risk score available at the
  simulation timestamp and chooses a feasible `ACCOUNT_HOLD`.
* **Highest Tainted Balance** uses current modeled tainted balance from the
  timestamped `TaintResult` and chooses a feasible account hold.
* **Highest Transaction Value** uses the largest future outbound transaction
  value observable in the graph and chooses a feasible account hold.
* **Maximum Immediate Recovery** uses simulated intercepted illicit capital,
  collateral, and stable candidate IDs. It does not use Pareto ranking.
* **AEGIS** is the unchanged multi-objective optimizer. It uses recovery,
  legitimate collateral, affected accounts, and affected edges after policy
  filtering.

The default command uses a deterministic causal graph-feature score when no
fitted ML scorer is injected. Callers evaluating a fitted project ML model
can pass it to `run_benchmark(risk_scorer=...)`; the scorer must only inspect
data available at the supplied timestamp.

## Metrics

Recovery and collateral are integer minor units. Efficiency is an exact
`Decimal` ratio of illicit capital intercepted to legitimate capital affected.
For positive recovery and zero collateral, the ratio is represented by the
recovery amount (there is no denominator to divide by); for zero recovery and
zero collateral it is explicitly `undefined` (`null` in JSON). This avoids a
silent divide-by-zero convention.

The report includes scenario-level outcomes, aggregate recovery/collateral,
affected accounts and edges, feasibility, intervention count, decision
latency, Pareto-efficient selections, recovery advantage, collateral
differences, ties, and failure findings. Cold-start scenarios are flagged and
reported separately; a new account is not treated as fraudulent merely
because it is new.

## Reproducibility and limitations

The generator seed and all selector tie-breaks are fixed. Output ordering is
canonical. Runtime is environment-dependent and is the only expected
non-deterministic field. Ground truth is used by the harness only to create
the evaluation taint seed and for post-hoc analysis, never by selectors.

This benchmark compares AEGIS against deterministic baseline strategies on the project's synthetic evaluation environment. It does not establish superiority over proprietary production systems.

Run:

```text
python scripts/benchmark_aegis.py
python scripts/benchmark_aegis.py --json
```
