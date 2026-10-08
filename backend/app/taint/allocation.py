"""Integer-only proportional allocation for pooled taint balances."""

from __future__ import annotations

from collections.abc import Mapping


def proportional_allocate(
    amount_minor_units: int, components: Mapping[str, int]
) -> dict[str, int]:
    """Allocate *amount_minor_units* proportionally with deterministic rounding.

    The largest-remainder method preserves integer-money conservation. Ties are
    resolved lexicographically by component key, never by mapping insertion or
    hash order.
    """
    if amount_minor_units < 0:
        raise ValueError("Cannot allocate a negative amount.")
    if any(value < 0 for value in components.values()):
        raise ValueError("Allocation components cannot be negative.")

    ordered = [(key, components[key]) for key in sorted(components)]
    total = sum(value for _, value in ordered)
    if amount_minor_units > total:
        raise ValueError("Cannot allocate more than the tracked balance.")
    if amount_minor_units == 0 or total == 0:
        return {key: 0 for key, _ in ordered}

    allocations: dict[str, int] = {}
    remainders: list[tuple[int, str]] = []
    allocated = 0
    for key, balance in ordered:
        base, remainder = divmod(amount_minor_units * balance, total)
        allocations[key] = base
        allocated += base
        remainders.append((remainder, key))

    for _, key in sorted(remainders, key=lambda item: (-item[0], item[1]))[
        : amount_minor_units - allocated
    ]:
        allocations[key] += 1
    return allocations
