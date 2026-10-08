# Multi-objective intervention optimizer

The intervention optimizer evaluates each `InterventionCandidate` with the
existing `CounterfactualSimulator` and never performs graph traversal,
provenance allocation, or taint replay itself. Its input is therefore the
simulator's independently reported capital, scope, and provenance components.

## Policy and Pareto selection

`OptimizationConstraints` are hard limits. A candidate that violates any
configured limit is infeasible and is not made competitive by a better score.
The current implementation supports single interventions; the model's
`maximum_interventions` field reserves policy space for future bounded plans.

Feasible candidates are compared using Pareto dominance over four independent
objectives:

* maximize modeled tainted capital intercepted;
* minimize modeled legitimate capital affected;
* minimize affected accounts; and
* minimize affected edges.

The Pareto frontier is the primary decision surface rather than an arbitrary
weighted sum. A weighted sum can hide a severe collateral trade-off behind a
chosen unit conversion or weight and can change its answer when policy
priorities change. Among frontier candidates, selection is deterministic:
recovery, collateral, recovery efficiency, affected accounts, affected edges,
and lexical intervention ID are considered in that order. Recovery efficiency
is `intercepted / max(1, collateral)` and is only a secondary tie-breaker.

Every result includes structured evidence: feasibility violations, Pareto
membership/rank, comparison reasons for competing candidates, selected
capital values, binding constraints, and simulator provenance confidence.
There is no LLM or automatic account action in this component.

## Future evaluator

The optimizer depends on a small evaluator protocol. The current
`ObservedFutureCounterfactualEvaluator` delegates directly to
`CounterfactualSimulator`. A future `ForecastAwareFutureEvaluator` can provide
forecast-aware rollouts and still return the same
`CounterfactualResult`-shaped trade-offs without changing policy or selection
logic. Forecast-aware simulation is intentionally not implemented here.
