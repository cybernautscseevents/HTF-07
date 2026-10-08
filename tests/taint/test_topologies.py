"""Fan-out, fan-in, multi-source, and observable shortfall tests."""

from __future__ import annotations

from backend.app.taint import TaintEngine, TaintSeed
from tests.taint.conftest import make_event, make_graph


def test_fan_out_and_fan_in_preserve_each_edge_and_total_taint() -> None:
    seed = make_event("e-seed", "V", "A", 100_000, 0)
    a_to_b = make_event("e-a-b", "A", "B", 50_000, 1)
    a_to_c = make_event("e-a-c", "A", "C", 50_000, 2)
    b_to_x = make_event("e-b-x", "B", "X", 50_000, 3)
    c_to_x = make_event("e-c-x", "C", "X", 50_000, 4)
    result = TaintEngine().run(
        make_graph(seed, a_to_b, a_to_c, b_to_x, c_to_x),
        [TaintSeed("case-A", seed.transaction_id, 100_000)],
    )

    assert [item.tainted_amount_minor_units for item in result.allocations] == [
        100_000, 50_000, 50_000, 50_000, 50_000
    ]
    x = next(balance for balance in result.account_balances if balance.account_id == "X")
    assert x.tainted_balance_minor_units == 100_000
    assert result.conservation[0].conservation_error_minor_units == 0


def test_multiple_case_sources_remain_separately_attributed_after_fan_in() -> None:
    seed_a = make_event("e-seed-a", "V1", "X", 100_000, 0)
    seed_b = make_event("e-seed-b", "V2", "X", 50_000, 1)
    outbound = make_event("e-out", "X", "Y", 75_000, 2)
    result = TaintEngine().run(
        make_graph(seed_a, seed_b, outbound),
        [
            TaintSeed("case-A", seed_a.transaction_id, 100_000),
            TaintSeed("case-B", seed_b.transaction_id, 50_000),
        ],
    )

    contributions = result.allocations[-1].source_contributions
    assert [(item.source_case_id, item.amount_minor_units) for item in contributions] == [
        ("case-A", 50_000), ("case-B", 25_000)
    ]
    assert all(item.conservation_error_minor_units == 0 for item in result.conservation)


def test_observable_balance_shortfall_never_manufactures_taint() -> None:
    seed = make_event("e-seed", "V", "X", 100_000, 0)
    oversized_outbound = make_event("e-out", "X", "Y", 200_000, 1)
    result = TaintEngine().run(
        make_graph(seed, oversized_outbound),
        [TaintSeed("case-A", seed.transaction_id, 100_000)],
    )

    allocation = result.allocations[-1]
    assert allocation.tainted_amount_minor_units == 100_000
    assert allocation.unattributed_amount_minor_units == 100_000
    assert result.shortfalls[0].shortfall_minor_units == 100_000
    y = next(balance for balance in result.account_balances if balance.account_id == "Y")
    assert y.tainted_balance_minor_units == 100_000
    assert y.clean_balance_minor_units == 100_000
