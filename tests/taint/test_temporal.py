"""Temporal causality, inactive-event, cold-start, and cross-bank coverage."""

from __future__ import annotations

from backend.app.taint import TaintEngine, TaintSeed
from contracts.enums import TransactionStatus
from scripts.generator import generate_cold_start_scenario, generate_cross_bank_scenario
from tests.taint.conftest import make_event, make_graph


def test_events_before_seed_do_not_receive_future_taint() -> None:
    early_outbound = make_event("e-early", "X", "Y", 100_000, 0)
    seed = make_event("e-seed", "V", "X", 100_000, 1)
    later_outbound = make_event("e-later", "X", "Z", 100_000, 2)
    result = TaintEngine().run(
        make_graph(early_outbound, seed, later_outbound),
        [TaintSeed("case-A", seed.transaction_id, 100_000)],
    )

    assert result.allocations[0].tainted_amount_minor_units == 0
    assert result.allocations[-1].tainted_amount_minor_units == 100_000


def test_equal_timestamps_use_graph_insertion_order_deterministically() -> None:
    seed = make_event("e-seed", "V", "X", 100_000, 0)
    same_time_outbound = make_event("e-out", "X", "Y", 100_000, 0)
    result = TaintEngine().run(
        make_graph(seed, same_time_outbound),
        [TaintSeed("case-A", seed.transaction_id, 100_000)],
    )
    assert [item.event_id for item in result.allocations] == ["e-seed", "e-out"]
    assert result.allocations[-1].tainted_amount_minor_units == 100_000


def test_inactive_events_do_not_propagate_taint() -> None:
    seed = make_event("e-seed", "V", "X", 100_000, 0)
    pending = make_event(
        "e-pending", "X", "Y", 100_000, 1, status=TransactionStatus.PENDING
    )
    result = TaintEngine().run(
        make_graph(seed, pending), [TaintSeed("case-A", seed.transaction_id, 100_000)]
    )
    assert [item.event_id for item in result.allocations] == ["e-seed"]
    assert result.inactive_event_ids == ("e-pending",)


def test_cold_start_and_cross_bank_generator_paths_are_traced() -> None:
    for scenario in (generate_cold_start_scenario(seed=42), generate_cross_bank_scenario(seed=42)):
        graph = make_graph(*scenario.transactions)
        seed_transaction_id = scenario.truth.seed_transaction_ids[0]
        seed_event = next(
            event for event in scenario.transactions if event.transaction_id == seed_transaction_id
        )
        result = TaintEngine().run(
            graph,
            [
                TaintSeed(
                    scenario.truth.case_id,
                    seed_transaction_id,
                    seed_event.amount_minor_units,
                )
            ],
        )
        source_id = f"{scenario.truth.case_id}:{seed_transaction_id}"
        assert len(result.allocations_for_source(source_id)) >= 2
        assert result.conservation[0].conservation_error_minor_units == 0
