"""Deterministic pooled-money provenance engine.

This is a model of the *observable* transaction graph, not a bank ledger or
legal tracing conclusion. It makes these explicit conventions:

* Explicit seed transactions inject their declared taint into the receiver;
  any seed amount not declared tainted is modeled as non-tainted observed flow.
* Active graph edges are processed once in the graph's chronological order.
  Equal timestamps retain the TemporalGraph index ordering.
* Each account is a pooled balance of clean and per-seed tainted capital.
  Outbound covered funds use proportional allocation with integer
  largest-remainder rounding.
* An observed outgoing amount above the sender's tracked balance creates a
  shortfall. No additional taint is created. The observed recipient amount is
  retained as non-tainted but explicitly ``unattributed`` flow.
* Taint is never destroyed by this engine, so conservation is source stock
  conservation: seed injection equals remaining modeled taint plus explicit
  modeled termination (currently zero). Edge volume is reported separately
  because repeated hops would otherwise double-count the same capital.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.taint.allocation import proportional_allocate
from backend.app.taint.models import (
    AccountTaintBalance,
    ObservableBalanceShortfall,
    SourceConservation,
    SourceContribution,
    TaintAllocation,
    TaintResult,
    TaintSeed,
)

_CLEAN_COMPONENT = "__clean__"


@dataclass(slots=True)
class _MutableBalance:
    clean_minor_units: int = 0
    tainted_minor_units: dict[str, int] = field(default_factory=dict)

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


class TaintEngine:
    """Run one deterministic chronological provenance simulation over a graph."""

    def run(self, graph: TemporalGraph, seeds: Iterable[TaintSeed]) -> TaintResult:
        """Compute modeled provenance for *seeds* using active graph events only."""
        ordered_seeds = tuple(sorted(seeds, key=lambda seed: seed.source_id))
        self._validate_unique_sources(ordered_seeds)

        all_events = graph.events_between(active_only=False)
        self._validate_unique_event_ids(all_events)
        active_events = graph.events_between(active_only=True)
        seeds_by_event = self._resolve_seeds(active_events, ordered_seeds)

        balances: dict[str, _MutableBalance] = {}
        allocations: list[TaintAllocation] = []
        shortfalls: list[ObservableBalanceShortfall] = []
        source_volume: dict[str, int] = defaultdict(int)
        source_lookup = {seed.source_id: seed for seed in ordered_seeds}

        for sequence, event in enumerate(active_events):
            event_seeds = seeds_by_event.get(event.event_id, ())
            if event_seeds:
                allocation = self._inject_seed_event(
                    event=event,
                    sequence=sequence,
                    seeds=event_seeds,
                    balances=balances,
                )
            else:
                allocation, shortfall = self._process_event(
                    event=event,
                    sequence=sequence,
                    balances=balances,
                    source_lookup=source_lookup,
                )
                if shortfall is not None:
                    shortfalls.append(shortfall)

            allocations.append(allocation)
            for contribution in allocation.source_contributions:
                source_volume[contribution.source_id] += contribution.amount_minor_units

        account_balances = self._freeze_balances(balances, source_lookup)
        conservation = self._conservation(
            seeds=ordered_seeds,
            balances=account_balances,
            source_volume=source_volume,
        )
        inactive_event_ids = tuple(
            event.event_id for event in all_events if not event.is_active_flow
        )
        return TaintResult(
            seeds=ordered_seeds,
            allocations=tuple(allocations),
            account_balances=account_balances,
            shortfalls=tuple(shortfalls),
            inactive_event_ids=inactive_event_ids,
            conservation=conservation,
        )

    @staticmethod
    def _validate_unique_sources(seeds: tuple[TaintSeed, ...]) -> None:
        source_ids = [seed.source_id for seed in seeds]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Duplicate taint seed source_id.")

    @staticmethod
    def _validate_unique_event_ids(events: list[object]) -> None:
        event_ids = [event.event_id for event in events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("TemporalGraph contains duplicate event_id values.")

    @staticmethod
    def _resolve_seeds(
        active_events: list[object], seeds: tuple[TaintSeed, ...]
    ) -> dict[str, tuple[TaintSeed, ...]]:
        by_transaction: dict[str, list[object]] = defaultdict(list)
        for event in active_events:
            by_transaction[event.transaction_id].append(event)

        grouped: dict[str, list[TaintSeed]] = defaultdict(list)
        for seed in seeds:
            matched = by_transaction.get(seed.transaction_id, [])
            if not matched:
                raise ValueError(
                    f"Seed transaction '{seed.transaction_id}' is not an active graph event."
                )
            if len(matched) != 1:
                raise ValueError(
                    f"Seed transaction '{seed.transaction_id}' is ambiguous in active graph events."
                )
            event = matched[0]
            grouped[event.event_id].append(seed)

        for event_id, event_seeds in grouped.items():
            event = next(event for event in active_events if event.event_id == event_id)
            if sum(seed.tainted_amount_minor_units for seed in event_seeds) > event.amount_minor_units:
                raise ValueError(
                    f"Seed taint exceeds transaction amount for event '{event_id}'."
                )
        return {
            event_id: tuple(sorted(event_seeds, key=lambda seed: seed.source_id))
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
            if amount > 0
        )

    def _inject_seed_event(
        self, event: object, sequence: int, seeds: tuple[TaintSeed, ...], balances: dict[str, _MutableBalance]
    ) -> TaintAllocation:
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
        event: object,
        sequence: int,
        balances: dict[str, _MutableBalance],
        source_lookup: dict[str, TaintSeed],
    ) -> tuple[TaintAllocation, ObservableBalanceShortfall | None]:
        sender = balances.setdefault(event.sender_id, _MutableBalance())
        before = sender.tracked_total
        tainted_before = sender.tainted_total
        covered_amount = min(event.amount_minor_units, before)
        component_allocations = proportional_allocate(covered_amount, sender.components())
        sender.debit(component_allocations)

        tainted_amounts = {
            source_id: amount
            for source_id, amount in component_allocations.items()
            if source_id != _CLEAN_COMPONENT and amount > 0
        }
        tainted_amount = sum(tainted_amounts.values())
        clean_amount = component_allocations.get(_CLEAN_COMPONENT, 0)
        shortfall_amount = event.amount_minor_units - covered_amount

        # The recipient sees the complete observed transaction. The shortfall
        # portion is non-tainted in the model but is separately exposed as
        # unattributed rather than silently treated as fully explained capital.
        balances.setdefault(event.receiver_id, _MutableBalance()).credit(
            clean_amount + shortfall_amount, tainted_amounts
        )
        allocation = TaintAllocation(
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
        shortfall = None
        if shortfall_amount:
            shortfall = ObservableBalanceShortfall(
                event_id=event.event_id,
                transaction_id=event.transaction_id,
                sender_account_id=event.sender_id,
                receiver_account_id=event.receiver_id,
                occurred_at=event.occurred_at,
                transaction_amount_minor_units=event.amount_minor_units,
                tracked_balance_before_minor_units=before,
                shortfall_minor_units=shortfall_amount,
            )
        return allocation, shortfall

    def _freeze_balances(
        self,
        balances: dict[str, _MutableBalance],
        source_lookup: dict[str, TaintSeed],
    ) -> tuple[AccountTaintBalance, ...]:
        return tuple(
            AccountTaintBalance(
                account_id=account_id,
                clean_balance_minor_units=balance.clean_minor_units,
                tainted_balances=self._contributions(
                    balance.tainted_minor_units, source_lookup
                ),
            )
            for account_id, balance in sorted(balances.items())
            if balance.tracked_total > 0
        )

    @staticmethod
    def _conservation(
        seeds: tuple[TaintSeed, ...],
        balances: tuple[AccountTaintBalance, ...],
        source_volume: dict[str, int],
    ) -> tuple[SourceConservation, ...]:
        remaining_by_source: dict[str, int] = defaultdict(int)
        for balance in balances:
            for contribution in balance.tainted_balances:
                remaining_by_source[contribution.source_id] += contribution.amount_minor_units
        return tuple(
            SourceConservation(
                source_id=seed.source_id,
                source_case_id=seed.case_id,
                seed_transaction_id=seed.transaction_id,
                initial_tainted_amount_minor_units=seed.tainted_amount_minor_units,
                propagated_edge_volume_minor_units=source_volume[seed.source_id],
                remaining_observable_tainted_amount_minor_units=remaining_by_source[
                    seed.source_id
                ],
                terminated_tainted_amount_minor_units=0,
                conservation_error_minor_units=(
                    seed.tainted_amount_minor_units
                    - remaining_by_source[seed.source_id]
                ),
            )
            for seed in seeds
        )
