"""Immutable data structures produced by the deterministic taint engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TaintSeed:
    """An explicit fraud-proceeds injection into a seed transaction receiver."""

    case_id: str
    transaction_id: str
    tainted_amount_minor_units: int

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("TaintSeed.case_id must be non-empty.")
        if not self.transaction_id:
            raise ValueError("TaintSeed.transaction_id must be non-empty.")
        if self.tainted_amount_minor_units <= 0:
            raise ValueError("Taint seed amount must be greater than zero.")

    @property
    def source_id(self) -> str:
        """Stable per-seed provenance identity, including its case context."""
        return f"{self.case_id}:{self.transaction_id}"


@dataclass(frozen=True, slots=True)
class SourceContribution:
    """The modeled amount on an edge attributable to one explicit seed."""

    source_id: str
    source_case_id: str
    seed_transaction_id: str
    amount_minor_units: int


@dataclass(frozen=True, slots=True)
class TaintAllocation:
    """Provenance allocation for one active graph edge.

    ``unattributed_amount_minor_units`` is the observed amount that exceeded
    the sender's tracked balance. It is not made tainted; its provenance is
    explicitly unknown to this observable-flow model.
    """

    event_id: str
    transaction_id: str
    occurred_at: datetime
    sequence: int
    sender_account_id: str
    receiver_account_id: str
    transaction_amount_minor_units: int
    tracked_balance_before_minor_units: int
    tainted_amount_minor_units: int
    clean_amount_minor_units: int
    unattributed_amount_minor_units: int
    taint_ratio_numerator: int
    taint_ratio_denominator: int
    allocation_method: str
    source_contributions: tuple[SourceContribution, ...]

    @property
    def observable_shortfall_minor_units(self) -> int:
        return self.unattributed_amount_minor_units


@dataclass(frozen=True, slots=True)
class AccountTaintBalance:
    """Current modeled observable balance for one account."""

    account_id: str
    clean_balance_minor_units: int
    tainted_balances: tuple[SourceContribution, ...]

    @property
    def tainted_balance_minor_units(self) -> int:
        return sum(item.amount_minor_units for item in self.tainted_balances)

    @property
    def tracked_balance_minor_units(self) -> int:
        return self.clean_balance_minor_units + self.tainted_balance_minor_units


@dataclass(frozen=True, slots=True)
class ObservableBalanceShortfall:
    """An outgoing observed transfer beyond the sender's tracked balance."""

    event_id: str
    transaction_id: str
    sender_account_id: str
    receiver_account_id: str
    occurred_at: datetime
    transaction_amount_minor_units: int
    tracked_balance_before_minor_units: int
    shortfall_minor_units: int


@dataclass(frozen=True, slots=True)
class SourceConservation:
    """Per-seed conservation report.

    ``propagated_edge_volume_minor_units`` is deliberately a movement metric,
    not a stock term: money can traverse more than one edge and therefore may
    exceed the seed amount. Conservation is checked against remaining modeled
    source balance plus any explicit modeled termination amount.
    """

    source_id: str
    source_case_id: str
    seed_transaction_id: str
    initial_tainted_amount_minor_units: int
    propagated_edge_volume_minor_units: int
    remaining_observable_tainted_amount_minor_units: int
    terminated_tainted_amount_minor_units: int
    conservation_error_minor_units: int


@dataclass(frozen=True, slots=True)
class TaintResult:
    """Complete deterministic provenance result for a graph and seed set."""

    seeds: tuple[TaintSeed, ...]
    allocations: tuple[TaintAllocation, ...]
    account_balances: tuple[AccountTaintBalance, ...]
    shortfalls: tuple[ObservableBalanceShortfall, ...]
    inactive_event_ids: tuple[str, ...]
    conservation: tuple[SourceConservation, ...]

    def allocations_for_source(self, source_id: str) -> tuple[TaintAllocation, ...]:
        """Return all edge allocations carrying the requested seed's taint."""
        return tuple(
            allocation
            for allocation in self.allocations
            if any(
                contribution.source_id == source_id
                and contribution.amount_minor_units > 0
                for contribution in allocation.source_contributions
            )
        )

    def current_tainted_accounts(self) -> tuple[AccountTaintBalance, ...]:
        """Return accounts that currently contain modeled tainted capital."""
        return tuple(
            balance
            for balance in self.account_balances
            if balance.tainted_balance_minor_units > 0
        )

    def terminal_tainted_accounts(self) -> tuple[AccountTaintBalance, ...]:
        """Return modeled taint remaining at the end of this graph horizon.

        "Terminal" means no later active event in the processed observation
        window moved that taint; it does not imply a legal or real-world stop.
        """
        return self.current_tainted_accounts()
