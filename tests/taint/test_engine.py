"""Core deterministic provenance behavior and validation."""

from __future__ import annotations

import pytest

from backend.app.taint import TaintEngine, TaintSeed, trace_for_source
from tests.taint.conftest import make_event, make_graph


def test_simple_chain_preserves_seed_taint_and_trace() -> None:
    seed_event = make_event("e-seed", "V", "A", 100_000, 0)
    first_hop = make_event("e-a-b", "A", "B", 100_000, 1)
    second_hop = make_event("e-b-c", "B", "C", 100_000, 2)
    result = TaintEngine().run(
        make_graph(seed_event, first_hop, second_hop),
        [TaintSeed("case-A", seed_event.transaction_id, 100_000)],
    )

    source_id = "case-A:tx-e-seed"
    assert [allocation.event_id for allocation in result.allocations_for_source(source_id)] == [
        "e-seed", "e-a-b", "e-b-c"
    ]
    assert trace_for_source(result, source_id).downstream_accounts == ("A", "B", "C")
    assert result.current_tainted_accounts()[0].account_id == "C"
    assert result.current_tainted_accounts()[0].tainted_balance_minor_units == 100_000
    assert result.conservation[0].conservation_error_minor_units == 0


def test_seed_validation_rejects_zero_amount_and_unknown_transaction() -> None:
    seed_event = make_event("e-seed", "V", "A", 100, 0)
    graph = make_graph(seed_event)
    with pytest.raises(ValueError, match="greater than zero"):
        TaintSeed("case-A", seed_event.transaction_id, 0)
    with pytest.raises(ValueError, match="not an active"):
        TaintEngine().run(graph, [TaintSeed("case-A", "missing", 1)])
    with pytest.raises(ValueError, match="exceeds"):
        TaintEngine().run(graph, [TaintSeed("case-A", seed_event.transaction_id, 101)])


def test_zero_value_event_is_deterministic_and_does_not_create_taint() -> None:
    seed_event = make_event("e-seed", "V", "A", 100, 0)
    zero_event = make_event("e-zero", "A", "B", 0, 1)
    result = TaintEngine().run(
        make_graph(seed_event, zero_event),
        [TaintSeed("case-A", seed_event.transaction_id, 100)],
    )

    zero_allocation = result.allocations[-1]
    assert zero_allocation.tainted_amount_minor_units == 0
    assert zero_allocation.taint_ratio_numerator == 100
    assert zero_allocation.taint_ratio_denominator == 100
    assert result.current_tainted_accounts()[0].account_id == "A"


def test_duplicate_event_ids_are_rejected_before_processing() -> None:
    seed_event = make_event("e-duplicate", "V", "A", 100, 0)
    graph = make_graph(seed_event, seed_event)
    with pytest.raises(ValueError, match="duplicate event_id"):
        TaintEngine().run(
            graph, [TaintSeed("case-A", seed_event.transaction_id, 100)]
        )
