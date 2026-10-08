"""Exact, explicit metric calculations for intervention evaluation."""

from __future__ import annotations

from decimal import Decimal


def efficiency(intercepted: int, collateral: int) -> Decimal | None:
    """Return recovery per collateral unit; ``None`` means 0/0."""
    if intercepted < 0 or collateral < 0:
        raise ValueError("Capital values must be non-negative.")
    if collateral == 0:
        return Decimal(intercepted) if intercepted else None
    return Decimal(intercepted) / Decimal(collateral)


def aggregate_efficiency(recovery: int, collateral: int) -> Decimal | None:
    """Calculate aggregate efficiency without silently dividing by zero."""
    return efficiency(recovery, collateral)


def metric_dict(
    intercepted: int,
    collateral: int,
    accounts: int,
    edges: int,
) -> dict[str, int | str | None]:
    """Return a JSON-friendly exact metric payload."""
    ratio = efficiency(intercepted, collateral)
    return {
        "illicit_capital_intercepted": intercepted,
        "legitimate_capital_affected": collateral,
        "efficiency": None if ratio is None else str(ratio),
        "illicit_capital_per_rupee_legitimate": None if ratio is None else str(ratio),
        "affected_accounts": accounts,
        "affected_edges": edges,
    }
