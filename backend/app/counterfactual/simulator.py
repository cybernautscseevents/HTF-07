"""Deterministic counterfactual intervention simulator.

This module implements the core simulation engine.  Given a baseline
:class:`TemporalGraph` and :class:`TaintResult`, it evaluates what would
happen if a candidate intervention were applied at a specific simulation
time.

Design invariants
-----------------
* **No mutation** of the baseline graph or taint result.
* **Temporal rule**: only events with ``occurred_at > simulation_timestamp``
  may be affected.  Historical events remain unchanged.
* **No replacement routes**: taint that can no longer traverse a blocked
  edge remains upstream/residual.
* **No future leakage**: the simulator does not use future knowledge to
  reconstruct what an investigator would have known at ``t``.
* **Integer arithmetic** for all money fields.
* **Deterministic**: repeated runs with identical inputs produce identical
  outputs.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from typing import Iterable

from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.graph.temporal_index import EdgeData
from backend.app.taint.allocation import proportional_allocate
from backend.app.taint.models import (
    AccountTaintBalance,
    SourceContribution,
    TaintAllocation,
    TaintResult,
    TaintSeed,
)
from backend.app.counterfactual.models import (
    CounterfactualResult,
    InterventionCandidate,
    InterventionType,
    SourceInterceptionDetail,
)

_CLEAN_COMPONENT = "__clean__"


def _intervention_id(candidate: InterventionCandidate, sim_time: datetime) -> str:
    """Deterministic intervention ID derived from candidate and timestamp."""
    target = candidate.target_account_id or candidate.target_event_id or ""
    raw = f"{candidate.intervention_type.value}:{target}:{sim_time.isoformat()}"
    return f"cf-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


class _MutableBalance:
    """Mutable per-account balance tracker for counterfactual re-simulation.

    Mirrors the TaintEngine's internal balance bookkeeping but is created
    fresh for each counterfactual world.
    """

    __slots__ = ("clean_minor_units", "tainted_minor_units")

    def __init__(self) -> None:
        self.clean_minor_units: int = 0
        self.tainted_minor_units: dict[str, int] = {}

    @property
    def tainted_total(self) -> int:
        return sum(self.tainted_minor_units.values())

    @property
    def tracked_total(self) -> int:
        return self.clean_minor_units + self.tainted_total

    def components(self) -> dict[str, int]:
        return {
            _CLEAN_COMPONENT: self.clean_minor_units,
            **self.tainted_minor_units,
        }

    def debit(self, amounts: dict[str, int]) -> None:
        clean_amount = amounts.get(_CLEAN_COMPONENT, 0)
        self.clean_minor_units -= clean_amount
        if self.clean_minor_units < 0:
            raise AssertionError("Clean balance cannot become negative.")
        for source_id, amount in amounts.items():
            if source_id == _CLEAN_COMPONENT:
                continue
            remaining = self.tainted_minor_units.get(source_id, 0) - amount
            if remaining < 0:
                raise AssertionError("Tainted balance cannot become negative.")
            if remaining:
                self.tainted_minor_units[source_id] = remaining
            else:
                self.tainted_minor_units.pop(source_id, None)

    def credit(self, clean_amount: int, tainted_amounts: dict[str, int]) -> None:
        self.clean_minor_units += clean_amount
        for source_id, amount in tainted_amounts.items():
            if amount:
                self.tainted_minor_units[source_id] = (
                    self.tainted_minor_units.get(source_id, 0) + amount
                )


class CounterfactualSimulator:
    """Simulate counterfactual interventions against a baseline taint result.

    Usage::

        simulator = CounterfactualSimulator(graph, baseline_result)
        result = simulator.simulate(candidate, simulation_timestamp)
    """

    def __init__(
        self,
        graph: TemporalGraph,
        baseline_result: TaintResult,
    ) -> None:
        self._graph = graph
        self._baseline = baseline_result

        # Pre-index baseline allocations by event_id for efficient lookup
        self._baseline_alloc_by_event: dict[str, TaintAllocation] = {
            alloc.event_id: alloc for alloc in baseline_result.allocations
        }

    def simulate(
        self,
        candidate: InterventionCandidate,
        simulation_timestamp: datetime,
    ) -> CounterfactualResult:
        """Run one counterfactual simulation for *candidate* at *simulation_timestamp*.

        Parameters
        ----------
        candidate : InterventionCandidate
            The proposed intervention to evaluate.
        simulation_timestamp : datetime
            Only events with ``occurred_at > simulation_timestamp`` may be
            affected.  Events at or before this time are historical facts.

        Returns
        -------
        CounterfactualResult
            Complete trade-off analysis for this intervention.
        """
        if simulation_timestamp.tzinfo is None:
            raise ValueError("simulation_timestamp must be timezone-aware.")

        intervention_id = _intervention_id(candidate, simulation_timestamp)

        # Determine which future events are blocked by this intervention
        blocked_event_ids = self._resolve_blocked_events(
            candidate, simulation_timestamp
        )

        if not blocked_event_ids:
            # No future events affected — intervention has no impact
            return self._no_impact_result(
                intervention_id, candidate, simulation_timestamp
            )

        # Re-simulate taint propagation in the counterfactual world
        return self._simulate_counterfactual(
            intervention_id=intervention_id,
            candidate=candidate,
            simulation_timestamp=simulation_timestamp,
            blocked_event_ids=blocked_event_ids,
        )

    def _resolve_blocked_events(
        self,
        candidate: InterventionCandidate,
        sim_time: datetime,
    ) -> set[str]:
        """Determine which future events are blocked by this candidate."""
        blocked: set[str] = set()

        if candidate.intervention_type == InterventionType.ACCOUNT_HOLD:
            assert candidate.target_account_id is not None
            account_id = candidate.target_account_id
            # Block all future outbound active events from this account
            future_outgoing = self._graph.outgoing(
                account_id, start=sim_time, active_only=True
            )
            for edge in future_outgoing:
                if edge.occurred_at > sim_time:
                    blocked.add(edge.event_id)

        elif candidate.intervention_type == InterventionType.EDGE_HOLD:
            assert candidate.target_event_id is not None
            event_id = candidate.target_event_id
            # Block only this specific future event
            try:
                edge = self._graph.get_edge_by_event(event_id)
            except KeyError:
                return blocked  # event not in graph
            if edge.occurred_at > sim_time and edge.is_active_flow:
                blocked.add(event_id)

        return blocked

    def _simulate_counterfactual(
        self,
        intervention_id: str,
        candidate: InterventionCandidate,
        simulation_timestamp: datetime,
        blocked_event_ids: set[str],
    ) -> CounterfactualResult:
        """Re-simulate taint propagation with blocked events removed.

        The strategy:
        1. Replay all baseline allocations chronologically.
        2. For events at or before simulation_timestamp, apply the same
           allocation as the baseline (historical facts).
        3. For future events that are NOT blocked, re-compute allocation
           using the counterfactual balances.
        4. For future events that ARE blocked, skip them entirely —
           their taint remains upstream.
        """
        seeds = self._baseline.seeds
        source_lookup = {seed.source_id: seed for seed in seeds}

        # Build counterfactual balances by replaying chronologically
        balances: dict[str, _MutableBalance] = {}
        cf_allocations: list[TaintAllocation] = []

        # Get all active events in chronological order (matching engine ordering)
        all_active = self._graph.events_between(active_only=True)

        # Resolve seed events
        seeds_by_event = self._resolve_seeds(all_active, seeds)

        for sequence, event in enumerate(all_active):
            if event.event_id in blocked_event_ids:
                # This event is blocked in the counterfactual world — skip it.
                # Taint remains in the sender's balance.
                continue

            event_seeds = seeds_by_event.get(event.event_id, ())

            if event.occurred_at <= simulation_timestamp:
                # Historical event — replay exact baseline allocation
                baseline_alloc = self._baseline_alloc_by_event.get(event.event_id)
                if baseline_alloc is not None:
                    self._replay_baseline_allocation(
                        event, baseline_alloc, balances, source_lookup
                    )
                    cf_allocations.append(baseline_alloc)
            else:
                # Future event, not blocked — re-compute from counterfactual balances
                if event_seeds:
                    alloc = self._inject_seed_event(
                        event, sequence, event_seeds, balances
                    )
                else:
                    alloc = self._process_event(
                        event, sequence, balances, source_lookup
                    )
                cf_allocations.append(alloc)

        # Compute differences between baseline and counterfactual
        return self._compute_result(
            intervention_id=intervention_id,
            candidate=candidate,
            simulation_timestamp=simulation_timestamp,
            blocked_event_ids=blocked_event_ids,
            cf_balances=balances,
            cf_allocations=cf_allocations,
            source_lookup=source_lookup,
        )

    def _replay_baseline_allocation(
        self,
        event: EdgeData,
        alloc: TaintAllocation,
        balances: dict[str, _MutableBalance],
        source_lookup: dict[str, TaintSeed],
    ) -> None:
        """Replay a baseline allocation into counterfactual balances.

        For seed injection events, credit the receiver.
        For non-seed events, debit sender and credit receiver using
        the exact same amounts as the baseline.
        """
        if alloc.allocation_method == "seed_injection":
            # Seed injection: credit receiver with seed amounts
            tainted_amounts = {
                sc.source_id: sc.amount_minor_units
                for sc in alloc.source_contributions
            }
            clean_amount = alloc.clean_amount_minor_units
            balances.setdefault(event.receiver_id, _MutableBalance()).credit(
                clean_amount, tainted_amounts
            )
        else:
            # Non-seed: debit sender, credit receiver
            sender = balances.setdefault(event.sender_id, _MutableBalance())
            tracked = sender.tracked_total
            covered = min(alloc.transaction_amount_minor_units, tracked)

            if covered > 0:
                component_allocs = proportional_allocate(
                    covered, sender.components()
                )
                sender.debit(component_allocs)
                tainted_amounts = {
                    src: amt
                    for src, amt in component_allocs.items()
                    if src != _CLEAN_COMPONENT and amt > 0
                }
                clean_amount = component_allocs.get(_CLEAN_COMPONENT, 0)
                shortfall = alloc.transaction_amount_minor_units - covered
            else:
                tainted_amounts = {}
                clean_amount = 0
                shortfall = alloc.transaction_amount_minor_units

            balances.setdefault(event.receiver_id, _MutableBalance()).credit(
                clean_amount + shortfall, tainted_amounts
            )

    @staticmethod
    def _resolve_seeds(
        active_events: list[EdgeData],
        seeds: tuple[TaintSeed, ...],
    ) -> dict[str, tuple[TaintSeed, ...]]:
        """Map event IDs to their seeds (mirrors TaintEngine._resolve_seeds)."""
        by_transaction: dict[str, list[EdgeData]] = defaultdict(list)
        for event in active_events:
            by_transaction[event.transaction_id].append(event)

        grouped: dict[str, list[TaintSeed]] = defaultdict(list)
        for seed in seeds:
            matched = by_transaction.get(seed.transaction_id, [])
            if not matched or len(matched) != 1:
                continue
            event = matched[0]
            grouped[event.event_id].append(seed)

        return {
            event_id: tuple(sorted(event_seeds, key=lambda s: s.source_id))
            for event_id, event_seeds in grouped.items()
        }

    @staticmethod
    def _contributions(
        amounts: dict[str, int], source_lookup: dict[str, TaintSeed]
    ) -> tuple[SourceContribution, ...]:
        return tuple(
            SourceContribution(
                source_id=source_id,
                source_case_id=source_lookup[source_id].case_id,
                seed_transaction_id=source_lookup[source_id].transaction_id,
                amount_minor_units=amount,
            )
            for source_id, amount in sorted(amounts.items())
            if amount > 0 and source_id in source_lookup
        )

    def _inject_seed_event(
        self,
        event: EdgeData,
        sequence: int,
        seeds: tuple[TaintSeed, ...],
        balances: dict[str, _MutableBalance],
    ) -> TaintAllocation:
        """Inject a seed event into counterfactual balances."""
        source_amounts = {
            seed.source_id: seed.tainted_amount_minor_units for seed in seeds
        }
        source_lookup = {seed.source_id: seed for seed in seeds}
        tainted_amount = sum(source_amounts.values())
        clean_amount = event.amount_minor_units - tainted_amount
        balances.setdefault(event.receiver_id, _MutableBalance()).credit(
            clean_amount, source_amounts
        )
        return TaintAllocation(
            event_id=event.event_id,
            transaction_id=event.transaction_id,
            occurred_at=event.occurred_at,
            sequence=sequence,
            sender_account_id=event.sender_id,
            receiver_account_id=event.receiver_id,
            transaction_amount_minor_units=event.amount_minor_units,
            tracked_balance_before_minor_units=0,
            tainted_amount_minor_units=tainted_amount,
            clean_amount_minor_units=clean_amount,
            unattributed_amount_minor_units=0,
            taint_ratio_numerator=tainted_amount,
            taint_ratio_denominator=event.amount_minor_units,
            allocation_method="seed_injection",
            source_contributions=self._contributions(source_amounts, source_lookup),
        )

    def _process_event(
        self,
        event: EdgeData,
        sequence: int,
        balances: dict[str, _MutableBalance],
        source_lookup: dict[str, TaintSeed],
    ) -> TaintAllocation:
        """Process a non-seed event in the counterfactual world."""
        sender = balances.setdefault(event.sender_id, _MutableBalance())
        before = sender.tracked_total
        tainted_before = sender.tainted_total
        covered_amount = min(event.amount_minor_units, before)
        component_allocations = proportional_allocate(
            covered_amount, sender.components()
        )
        sender.debit(component_allocations)

        tainted_amounts = {
            source_id: amount
            for source_id, amount in component_allocations.items()
            if source_id != _CLEAN_COMPONENT and amount > 0
        }
        tainted_amount = sum(tainted_amounts.values())
        clean_amount = component_allocations.get(_CLEAN_COMPONENT, 0)
        shortfall_amount = event.amount_minor_units - covered_amount

        balances.setdefault(event.receiver_id, _MutableBalance()).credit(
            clean_amount + shortfall_amount, tainted_amounts
        )
        return TaintAllocation(
            event_id=event.event_id,
            transaction_id=event.transaction_id,
            occurred_at=event.occurred_at,
            sequence=sequence,
            sender_account_id=event.sender_id,
            receiver_account_id=event.receiver_id,
            transaction_amount_minor_units=event.amount_minor_units,
            tracked_balance_before_minor_units=before,
            tainted_amount_minor_units=tainted_amount,
            clean_amount_minor_units=clean_amount,
            unattributed_amount_minor_units=shortfall_amount,
            taint_ratio_numerator=tainted_before,
            taint_ratio_denominator=before,
            allocation_method="pooled_proportional_largest_remainder",
            source_contributions=self._contributions(tainted_amounts, source_lookup),
        )

    def _compute_result(
        self,
        intervention_id: str,
        candidate: InterventionCandidate,
        simulation_timestamp: datetime,
        blocked_event_ids: set[str],
        cf_balances: dict[str, _MutableBalance],
        cf_allocations: list[TaintAllocation],
        source_lookup: dict[str, TaintSeed],
    ) -> CounterfactualResult:
        """Compare baseline vs. counterfactual to produce the result.

        Taint is conserved (it doesn't disappear when an edge is blocked —
        it stays in the sender's balance).  Therefore we must compare
        per-account taint distributions, not just global totals.

        **Intercepted taint** = for each downstream account and each source,
        the taint that was present in the baseline but is no longer present
        in the counterfactual (because it remained trapped upstream of the
        blocked edge).
        """
        # Build baseline per-account per-source taint map
        baseline_acct_taint: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        for bal in self._baseline.account_balances:
            for sc in bal.tainted_balances:
                baseline_acct_taint[bal.account_id][sc.source_id] += (
                    sc.amount_minor_units
                )

        # Build counterfactual per-account per-source taint map
        cf_acct_taint: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        for account_id, bal in cf_balances.items():
            for source_id, amount in bal.tainted_minor_units.items():
                cf_acct_taint[account_id][source_id] += amount

        # Determine which accounts are "downstream" of the intervention.
        # For an account hold: the target account and all accounts reachable
        # from it after simulation_timestamp.
        # For an edge hold: the receiver of the blocked edge and beyond.
        # However, for correctness, we measure interception as the
        # per-account reduction in taint across ALL accounts.
        # An account that gained taint in the counterfactual (because taint
        # stayed upstream in it) is NOT intercepted — the taint just
        # didn't move.  Interception is only where taint decreased.

        # Compute per-source intercepted amounts
        all_accounts = set(baseline_acct_taint.keys()) | set(cf_acct_taint.keys())
        per_source_intercepted: dict[str, int] = defaultdict(int)
        per_source_residual: dict[str, int] = defaultdict(int)

        for account_id in all_accounts:
            baseline_sources = baseline_acct_taint.get(account_id, {})
            cf_sources = cf_acct_taint.get(account_id, {})
            all_sources = set(baseline_sources.keys()) | set(cf_sources.keys())

            for sid in all_sources:
                b_amt = baseline_sources.get(sid, 0)
                c_amt = cf_sources.get(sid, 0)
                if c_amt < b_amt:
                    # This account lost taint for this source in the counterfactual
                    per_source_intercepted[sid] += b_amt - c_amt
                per_source_residual[sid] += c_amt

        # Build source interception details
        total_intercepted = 0
        total_residual = 0
        source_details: list[SourceInterceptionDetail] = []

        for seed in self._baseline.seeds:
            sid = seed.source_id
            intercepted = per_source_intercepted.get(sid, 0)
            residual = per_source_residual.get(sid, 0)
            total_intercepted += intercepted
            total_residual += residual
            source_details.append(
                SourceInterceptionDetail(
                    source_id=sid,
                    source_case_id=seed.case_id,
                    intercepted_amount_minor_units=intercepted,
                    residual_amount_minor_units=residual,
                )
            )

        # Compute legitimate capital affected:
        # Sum of clean + unattributed amounts on blocked edges in the baseline
        legitimate_affected = 0
        for event_id in blocked_event_ids:
            baseline_alloc = self._baseline_alloc_by_event.get(event_id)
            if baseline_alloc is not None:
                legitimate_affected += baseline_alloc.clean_amount_minor_units
                legitimate_affected += baseline_alloc.unattributed_amount_minor_units

        # Determine affected accounts: sender and receiver of blocked edges
        affected_accounts: set[str] = set()
        for event_id in blocked_event_ids:
            baseline_alloc = self._baseline_alloc_by_event.get(event_id)
            if baseline_alloc is not None:
                affected_accounts.add(baseline_alloc.receiver_account_id)
                affected_accounts.add(baseline_alloc.sender_account_id)

        # Provenance coverage: fraction of intercepted taint with explicit
        # per-seed attribution.  Since the engine always attributes taint
        # to seeds, this is 1.0 when there is intercepted taint.
        if total_intercepted > 0:
            attributed = sum(
                d.intercepted_amount_minor_units for d in source_details
            )
            provenance_coverage = attributed / total_intercepted
        else:
            provenance_coverage = 1.0

        # Provenance confidence: degraded if any blocked edge had shortfalls
        shortfall_events = {sf.event_id for sf in self._baseline.shortfalls}
        has_shortfall_in_blocked = bool(blocked_event_ids & shortfall_events)
        provenance_confidence = 0.8 if has_shortfall_in_blocked else 1.0

        # Build explanation
        explanation = self._build_explanation(
            candidate=candidate,
            simulation_timestamp=simulation_timestamp,
            blocked_count=len(blocked_event_ids),
            intercepted=total_intercepted,
            legitimate=legitimate_affected,
            residual=total_residual,
        )

        # Remaining downstream taint: total taint still present in all
        # accounts in the counterfactual world.
        remaining_downstream = total_residual

        return CounterfactualResult(
            intervention_id=intervention_id,
            intervention_type=candidate.intervention_type,
            target_account_id=candidate.target_account_id,
            target_event_id=candidate.target_event_id,
            simulation_timestamp=simulation_timestamp,
            modeled_tainted_capital_intercepted=total_intercepted,
            modeled_legitimate_capital_affected=legitimate_affected,
            remaining_downstream_taint=remaining_downstream,
            number_of_affected_edges=len(blocked_event_ids),
            number_of_affected_accounts=len(affected_accounts),
            provenance_coverage=provenance_coverage,
            provenance_confidence=provenance_confidence,
            source_interception_details=tuple(
                sorted(source_details, key=lambda d: d.source_id)
            ),
            explanation=explanation,
            blocked_event_ids=tuple(sorted(blocked_event_ids)),
            affected_account_ids=tuple(sorted(affected_accounts)),
        )

    def _no_impact_result(
        self,
        intervention_id: str,
        candidate: InterventionCandidate,
        simulation_timestamp: datetime,
    ) -> CounterfactualResult:
        """Return a result when the intervention has no future events to block."""
        # Build source details showing zero interception
        source_details: list[SourceInterceptionDetail] = []
        total_remaining = 0
        for seed in self._baseline.seeds:
            remaining = sum(
                sc.amount_minor_units
                for bal in self._baseline.account_balances
                for sc in bal.tainted_balances
                if sc.source_id == seed.source_id
            )
            total_remaining += remaining
            source_details.append(
                SourceInterceptionDetail(
                    source_id=seed.source_id,
                    source_case_id=seed.case_id,
                    intercepted_amount_minor_units=0,
                    residual_amount_minor_units=remaining,
                )
            )

        target = candidate.target_account_id or candidate.target_event_id or ""
        explanation = (
            f"No future events affected by {candidate.intervention_type.value} "
            f"on {target} at {simulation_timestamp.isoformat()}. "
            f"All events at or before simulation time are historical facts."
        )

        return CounterfactualResult(
            intervention_id=intervention_id,
            intervention_type=candidate.intervention_type,
            target_account_id=candidate.target_account_id,
            target_event_id=candidate.target_event_id,
            simulation_timestamp=simulation_timestamp,
            modeled_tainted_capital_intercepted=0,
            modeled_legitimate_capital_affected=0,
            remaining_downstream_taint=total_remaining,
            number_of_affected_edges=0,
            number_of_affected_accounts=0,
            provenance_coverage=1.0,
            provenance_confidence=1.0,
            source_interception_details=tuple(
                sorted(source_details, key=lambda d: d.source_id)
            ),
            explanation=explanation,
            blocked_event_ids=(),
            affected_account_ids=(),
        )

    @staticmethod
    def _build_explanation(
        candidate: InterventionCandidate,
        simulation_timestamp: datetime,
        blocked_count: int,
        intercepted: int,
        legitimate: int,
        residual: int,
    ) -> str:
        target = candidate.target_account_id or candidate.target_event_id or ""
        return (
            f"Counterfactual {candidate.intervention_type.value} on {target} "
            f"at {simulation_timestamp.isoformat()}: "
            f"{blocked_count} future edge(s) blocked, "
            f"{intercepted} minor units of modeled tainted capital intercepted, "
            f"{legitimate} minor units of legitimate capital affected, "
            f"{residual} minor units of residual taint remaining."
        )
