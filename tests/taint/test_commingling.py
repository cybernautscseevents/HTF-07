"""Pooled proportional commingling behavior."""

from __future__ import annotations

from backend.app.taint import TaintEngine, TaintSeed
from tests.taint.conftest import make_event, make_graph


def test_commingled_clean_and_tainted_money_splits_proportionally() -> None:
    clean_inflow = make_event("e-clean", "CLEAN", "X", 100_000, 0)
    seed_event = make_event("e-seed", "V", "X", 100_000, 1)
    outbound = make_event("e-out", "X", "Y", 50_000, 2)
    result = TaintEngine().run(
        make_graph(clean_inflow, seed_event, outbound),
        [TaintSeed("case-A", seed_event.transaction_id, 100_000)],
    )

    allocation = result.allocations[-1]
    assert allocation.tainted_amount_minor_units == 25_000
    assert allocation.clean_amount_minor_units == 25_000
    assert allocation.unattributed_amount_minor_units == 0
    assert allocation.taint_ratio_numerator == 100_000
    assert allocation.taint_ratio_denominator == 200_000
    assert allocation.source_contributions[0].source_case_id == "case-A"
