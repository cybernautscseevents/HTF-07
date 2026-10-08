"""Convenience types for seed-specific provenance traces."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.taint.models import TaintAllocation, TaintResult


@dataclass(frozen=True, slots=True)
class ProvenanceTrace:
    """Chronological edge trace carrying taint from one explicit seed."""

    source_id: str
    allocations: tuple[TaintAllocation, ...]

    @property
    def downstream_accounts(self) -> tuple[str, ...]:
        """Distinct downstream accounts in deterministic first-seen order."""
        seen: set[str] = set()
        accounts: list[str] = []
        for allocation in self.allocations:
            if allocation.receiver_account_id not in seen:
                seen.add(allocation.receiver_account_id)
                accounts.append(allocation.receiver_account_id)
        return tuple(accounts)


def trace_for_source(result: TaintResult, source_id: str) -> ProvenanceTrace:
    """Build a seed-specific trace from already computed allocation records."""
    return ProvenanceTrace(
        source_id=source_id,
        allocations=result.allocations_for_source(source_id),
    )
