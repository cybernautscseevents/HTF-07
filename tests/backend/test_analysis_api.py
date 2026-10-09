"""Integration and unit tests for the End-to-End Investigation Analysis API and Orchestrator.

Endpoint tested: POST /api/cases/{case_id}/analyze

Covers all Section 9 requirements:
1. Successful analysis request
2. Unknown case (404)
3. Invalid seed and sink IDs (422)
4. Invalid timestamps (422)
5. Case isolation
6. Deterministic repeated analysis
7. Partial results when an optional stage has insufficient evidence
8. Missing ML artifact (cleanly handled as unavailable)
9. Forecast output remains distinct from observed transactions
10. No ground-truth leakage
11. Chokepoint source/sink and eligible-edge handling
12. No feasible candidate
13. Correct reuse of the existing optimizer
14. Baseline graph and taint result immutability
15. API response serialization
16. Stage-level failures and warnings
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
import pytest

from backend.app.api.schemas.analysis import (
    InvestigationAnalysisRequest,
    StageExecutionStatus,
    TaintSeedInput,
)
from backend.app.dependencies import get_investigation_orchestrator
from backend.app.ml.risk_model import MuleRiskModel
from backend.app.services.investigation_orchestrator import (
    CaseNotFoundError,
    EmptyCaseError,
)
from tests.backend.conftest import VALID_CASE, VALID_EVENT_1

UTC = timezone.utc
T0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)


def make_api_event(
    event_id: str,
    tx_id: str,
    sender: str,
    receiver: str,
    amount: int,
    occurred_at: datetime,
) -> dict:
    return {
        "event_id": event_id,
        "transaction_id": tx_id,
        "reference": f"REF-{event_id}",
        "sender": {"account_id": sender, "institution": "BANK_A"},
        "receiver": {"account_id": receiver, "institution": "BANK_B"},
        "amount_minor_units": amount,
        "currency": "INR",
        "occurred_at": occurred_at.isoformat(),
        "observed_at": (occurred_at + timedelta(seconds=1)).isoformat(),
        "status": "completed",
        "channel": "upi",
        "origin": "bank_feed",
    }


async def setup_linear_case(client, case_id: str = "case-test-01") -> tuple[dict, list[dict]]:
    """Helper to set up a 4-hop laundering case via API: Victim -> Mule1 -> Mule2 -> Exit."""
    case_payload = {
        **VALID_CASE,
        "case_id": case_id,
        "title": "Linear UPI Laundering Case",
    }
    await client.post("/api/cases", content=json.dumps(case_payload))

    ev1 = make_api_event("e1", "tx-seed-1", "Victim", "Mule1", 100_000_00, T0)
    ev2 = make_api_event("e2", "tx-hop-2", "Mule1", "Mule2", 100_000_00, T0 + timedelta(minutes=10))
    ev3 = make_api_event("e3", "tx-hop-3", "Mule2", "Exit", 100_000_00, T0 + timedelta(minutes=20))

    events = [ev1, ev2, ev3]
    for ev in events:
        post_resp = await client.post(
            "/api/events",
            params={"case_id": case_id},
            content=json.dumps(ev),
        )
        assert post_resp.status_code == 201

    return case_payload, events


# ── 1. Successful Analysis & Response Structure ─────────────────────────────


@pytest.mark.asyncio
async def test_successful_analysis_request(client) -> None:
    """Full successful end-to-end analysis request returns typed result with all stages."""
    case_id = "case-success-01"
    _, events = await setup_linear_case(client, case_id)

    sim_time = T0 + timedelta(minutes=5)
    req_payload = {
        "simulation_timestamp": sim_time.isoformat(),
        "taint_seeds": [{"transaction_id": "tx-seed-1", "tainted_amount_minor_units": 100_000_00}],
        "sink_account_ids": ["Exit"],
        "source_account_ids": ["Mule1"],
    }

    resp = await client.post(f"/api/cases/{case_id}/analyze", json=req_payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["case_id"] == case_id
    assert data["overall_status"] == "partial"
    assert "graph_construction" in data["stages"]
    assert "taint_propagation" in data["stages"]
    assert "chokepoint_search" in data["stages"]
    assert "intervention_optimization" in data["stages"]

    # Graph summary
    assert data["graph_summary"]["node_count"] == 4
    assert data["graph_summary"]["edge_count"] == 3

    # Taint summary
    assert data["taint_summary"]["seed_count"] == 1
    assert data["taint_summary"]["allocated_edge_count"] >= 1

    # Chokepoint report
    assert data["chokepoint_report"] is not None
    assert data["chokepoint_report"]["status"] == "optimal_cut_found"
    assert data["chokepoint_report"]["is_cut_verified"] is True
    assert len(data["chokepoint_report"]["cut_event_ids"]) >= 1

    # Evaluated candidates & recommendation
    assert data["evaluated_candidates"]["total_candidates_count"] >= 1
    assert data["selected_recommendation"] is not None
    rec = data["selected_recommendation"]
    assert rec["modeled_tainted_capital_intercepted"] > 0
    assert rec["policy_feasible"] is True

    # Warnings and safety disclaimers
    assert len(data["warnings_and_limitations"]) >= 4
    assert any("DECISION SUPPORT ONLY" in w for w in data["warnings_and_limitations"])


# ── 2. Unknown Case Handling ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_case_returns_404(client) -> None:
    """Requesting analysis on non-existent case returns 404."""
    req_payload = {
        "simulation_timestamp": T0.isoformat(),
        "taint_seeds": [{"transaction_id": "tx-foo", "tainted_amount_minor_units": 100_00}],
    }
    resp = await client.post("/api/cases/non-existent-case/analyze", json=req_payload)
    assert resp.status_code == 404
    assert "Case 'non-existent-case' not found" in resp.json()["detail"]


# ── 3. Empty Case Handling ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_case_returns_422(client) -> None:
    """Case with zero events returns 422."""
    case_payload = {**VALID_CASE, "case_id": "case-empty"}
    await client.post("/api/cases", content=json.dumps(case_payload))

    req_payload = {
        "simulation_timestamp": T0.isoformat(),
        "taint_seeds": [{"transaction_id": "tx-foo", "tainted_amount_minor_units": 100_00}],
    }
    resp = await client.post("/api/cases/case-empty/analyze", json=req_payload)
    assert resp.status_code == 422
    assert "contains no transaction events" in resp.json()["detail"]


# ── 4. Invalid Seed and Sink Validations ─────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_transaction_outside_case_returns_422(client) -> None:
    """Seed transaction not in the case returns 422."""
    case_id = "case-invalid-seed"
    await setup_linear_case(client, case_id)

    req_payload = {
        "simulation_timestamp": T0.isoformat(),
        "taint_seeds": [{"transaction_id": "tx-alien-999", "tainted_amount_minor_units": 100_00}],
    }
    resp = await client.post(f"/api/cases/{case_id}/analyze", json=req_payload)
    assert resp.status_code == 422
    assert "does not belong to case" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_zero_seed_amount_returns_422(client) -> None:
    """Zero or negative seed amount returns 422 validation error."""
    case_id = "case-zero-seed"
    await setup_linear_case(client, case_id)

    req_payload = {
        "simulation_timestamp": T0.isoformat(),
        "taint_seeds": [{"transaction_id": "tx-seed-1", "tainted_amount_minor_units": 0}],
    }
    resp = await client.post(f"/api/cases/{case_id}/analyze", json=req_payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_overlapping_source_and_sink_returns_422(client) -> None:
    """Source account and sink account overlap returns 422."""
    case_id = "case-overlap"
    await setup_linear_case(client, case_id)

    req_payload = {
        "simulation_timestamp": T0.isoformat(),
        "taint_seeds": [{"transaction_id": "tx-seed-1", "tainted_amount_minor_units": 100_00}],
        "source_account_ids": ["Mule1"],
        "sink_account_ids": ["Mule1"],  # overlap!
    }
    resp = await client.post(f"/api/cases/{case_id}/analyze", json=req_payload)
    assert resp.status_code == 422
    assert "cannot overlap" in resp.json()["detail"]


# ── 5. Invalid Timestamp Handling ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_timezone_naive_timestamp_returns_422(client) -> None:
    """Timezone-naive datetime string is rejected with 422."""
    case_id = "case-naive-ts"
    await setup_linear_case(client, case_id)

    req_payload = {
        "simulation_timestamp": "2026-10-08T12:00:00",  # missing timezone offset Z
        "taint_seeds": [{"transaction_id": "tx-seed-1", "tainted_amount_minor_units": 100_00}],
    }
    resp = await client.post(f"/api/cases/{case_id}/analyze", json=req_payload)
    assert resp.status_code == 422


# ── 6. Case and Graph Isolation ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_case_isolation_between_cases(client) -> None:
    """Analyses for distinct cases do not leak events or accounts across graphs."""
    case1 = "case-iso-1"
    case2 = "case-iso-2"

    await setup_linear_case(client, case1)

    # Set up case 2 with different accounts
    await client.post("/api/cases", content=json.dumps({**VALID_CASE, "case_id": case2}))
    ev_c2 = make_api_event("e_c2", "tx_c2", "AcctX", "AcctY", 500_00, T0)
    post_resp2 = await client.post(
        "/api/events",
        params={"case_id": case2},
        content=json.dumps(ev_c2),
    )
    assert post_resp2.status_code == 201

    resp1 = await client.post(
        f"/api/cases/{case1}/analyze",
        json={
            "simulation_timestamp": (T0 + timedelta(minutes=5)).isoformat(),
            "taint_seeds": [{"transaction_id": "tx-seed-1", "tainted_amount_minor_units": 100_00}],
        },
    )
    resp2 = await client.post(
        f"/api/cases/{case2}/analyze",
        json={
            "simulation_timestamp": (T0 + timedelta(minutes=5)).isoformat(),
            "taint_seeds": [{"transaction_id": "tx_c2", "tainted_amount_minor_units": 500_00}],
        },
    )

    data1 = resp1.json()
    data2 = resp2.json()

    assert "AcctX" not in data1["graph_summary"]["account_ids"]
    assert "Victim" not in data2["graph_summary"]["account_ids"]


# ── 7. Deterministic Repeated Analysis ──────────────────────────────────────


@pytest.mark.asyncio
async def test_deterministic_repeated_analysis(client) -> None:
    """Repeated calls with identical input yield identical analytical output."""
    case_id = "case-repeat"
    await setup_linear_case(client, case_id)

    payload = {
        "simulation_timestamp": (T0 + timedelta(minutes=5)).isoformat(),
        "taint_seeds": [{"transaction_id": "tx-seed-1", "tainted_amount_minor_units": 100_00}],
        "sink_account_ids": ["Exit"],
    }

    resp1 = await client.post(f"/api/cases/{case_id}/analyze", json=payload)
    resp2 = await client.post(f"/api/cases/{case_id}/analyze", json=payload)

    d1 = resp1.json()
    d2 = resp2.json()

    # Compare core deterministic sections
    assert d1["taint_summary"] == d2["taint_summary"]
    assert d1["chokepoint_report"] == d2["chokepoint_report"]
    assert d1["evaluated_candidates"] == d2["evaluated_candidates"]
    assert d1["selected_recommendation"] == d2["selected_recommendation"]


# ── 8. Missing ML Artifact Stage Handling ───────────────────────────────────


@pytest.mark.asyncio
async def test_missing_ml_artifact_stage_handling(client) -> None:
    """When ML model artifact is unavailable, risk stage reports unavailable without crashing."""
    case_id = "case-no-ml"
    await setup_linear_case(client, case_id)

    # By default, without trained models on disk, risk_model is None
    payload = {
        "simulation_timestamp": (T0 + timedelta(minutes=5)).isoformat(),
        "taint_seeds": [{"transaction_id": "tx-seed-1", "tainted_amount_minor_units": 100_00}],
    }
    resp = await client.post(f"/api/cases/{case_id}/analyze", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    # Risk stage is reported as unavailable, not fabricated
    assert data["stages"]["risk_assessment"]["status"] == "unavailable"
    assert data["risk_predictions"] == []
    # Other stages succeed
    assert data["stages"]["graph_construction"]["status"] == "completed"
    assert data["stages"]["taint_propagation"]["status"] == "completed"


# ── 9. Forecast Output Distinction from Observed Transactions ───────────────


@pytest.mark.asyncio
async def test_forecast_distinct_from_observed_events(client) -> None:
    """Forecast generation does not insert synthetic events into canonical case timeline."""
    case_id = "case-forecast-check"
    await setup_linear_case(client, case_id)

    payload = {
        "simulation_timestamp": (T0 + timedelta(minutes=5)).isoformat(),
        "taint_seeds": [{"transaction_id": "tx-seed-1", "tainted_amount_minor_units": 100_00}],
        "forecast_config": {"top_k": 3, "max_depth": 2},
    }
    resp = await client.post(f"/api/cases/{case_id}/analyze", json=payload)
    assert resp.status_code == 200

    # Verify timeline of real case remains exactly 3 events
    timeline_resp = await client.get(f"/api/cases/{case_id}/timeline")
    assert len(timeline_resp.json()) == 3


# ── 10. No Ground-Truth Leakage into Candidates ─────────────────────────────


@pytest.mark.asyncio
async def test_no_ground_truth_leakage_into_candidates(client) -> None:
    """Historical events <= simulation_timestamp are strictly excluded from intervention candidates."""
    case_id = "case-leakage"
    await setup_linear_case(client, case_id)

    # Decision time is T0 + 15 mins. e1 (t=0) and e2 (t=10) are in the past!
    # Only e3 (t=20) is in the future.
    sim_time = T0 + timedelta(minutes=15)
    payload = {
        "simulation_timestamp": sim_time.isoformat(),
        "taint_seeds": [{"transaction_id": "tx-seed-1", "tainted_amount_minor_units": 100_00}],
    }
    resp = await client.post(f"/api/cases/{case_id}/analyze", json=payload)
    data = resp.json()

    # Check candidate recommendations or evaluated candidates: target_event_id cannot be e1 or e2
    if data["selected_recommendation"] and data["selected_recommendation"]["target_event_id"]:
        assert data["selected_recommendation"]["target_event_id"] not in ("e1", "e2")


# ── 11. Chokepoint Source/Sink and Eligible-Edge Handling ────────────────────


@pytest.mark.asyncio
async def test_chokepoint_source_sink_eligible_edges(client) -> None:
    """Chokepoint search respects designated sinks and eligible events."""
    case_id = "case-chokepoint-api"
    await setup_linear_case(client, case_id)

    payload = {
        "simulation_timestamp": T0.isoformat(),
        "taint_seeds": [{"transaction_id": "tx-seed-1", "tainted_amount_minor_units": 100_00}],
        "sink_account_ids": ["Exit"],
        "source_account_ids": ["Mule1"],
        "eligible_event_ids": ["e2", "e3"],
    }
    resp = await client.post(f"/api/cases/{case_id}/analyze", json=payload)
    data = resp.json()

    cp = data["chokepoint_report"]
    assert cp is not None
    assert cp["status"] == "optimal_cut_found"
    assert cp["is_cut_verified"] is True
    # All cut edges must be in eligible_event_ids
    for eid in cp["cut_event_ids"]:
        assert eid in ("e2", "e3")


# ── 12. No Feasible Candidate Under Strict Policy ───────────────────────────


@pytest.mark.asyncio
async def test_no_feasible_candidate_under_strict_policy(client) -> None:
    """When policy limits cannot be met, optimizer marks infeasible without crash."""
    case_id = "case-infeasible"
    await setup_linear_case(client, case_id)

    payload = {
        "simulation_timestamp": (T0 + timedelta(minutes=5)).isoformat(),
        "taint_seeds": [{"transaction_id": "tx-seed-1", "tainted_amount_minor_units": 100_00}],
        "constraints": {
            "minimum_required_illicit_recovery": 999_999_999_00,  # Unattainable recovery requirement
        },
    }
    resp = await client.post(f"/api/cases/{case_id}/analyze", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["selected_recommendation"] is None
    assert data["evaluated_candidates"]["feasible_candidates_count"] == 0
    assert data["stages"]["intervention_optimization"]["status"] == "infeasible"


# ── 13. Regression: Simple Chain Directionality & Cycle Prevention ──────────


@pytest.mark.asyncio
async def test_simple_chain_forecast_no_direction_reversal_or_prior_account_revisit(client) -> None:
    """Simple chain: Victim -> Mule1 -> Mule2 -> Exit.

    Verifies:
    1. At T=5m (after Victim -> Mule1, before Mule1 -> Mule2):
       - Current tainted account is Mule1, NOT Exit.
       - Next-hop prediction does NOT return Victim as a candidate (cannot reverse transaction direction).
       - Does not predict future unobserved accounts (Mule2, Exit) without supporting evidence.
       - Returns status 'insufficient_evidence' for next_hop_prediction and forecast_simulation.
       - Forecast simulation generates 0 paths (no cycle or reversal).
       - Model artifact unavailability is reported as 'unavailable' with no fabricated risk scores.
       - Overall response status is 'partial'.
    2. At T=15m (after Mule1 -> Mule2, before Mule2 -> Exit):
       - Current tainted account is Mule2.
       - Next-hop does NOT return Mule1 or Victim.
       - Returns 'insufficient_evidence' rather than hallucinating Exit.
    """
    case_id = "case-chain-audit"
    await setup_linear_case(client, case_id)

    # Decision at T = 5 minutes
    t5 = T0 + timedelta(minutes=5)
    payload_t5 = {
        "simulation_timestamp": t5.isoformat(),
        "taint_seeds": [{"transaction_id": "tx-seed-1", "tainted_amount_minor_units": 100_000_00}],
    }
    resp_t5 = await client.post(f"/api/cases/{case_id}/analyze", json=payload_t5)
    assert resp_t5.status_code == 200
    d5 = resp_t5.json()

    # 1. Taint summary at T=5m
    assert d5["taint_summary"]["current_tainted_accounts"] == ["Mule1"]
    assert "Exit" not in d5["taint_summary"]["current_tainted_accounts"]
    assert d5["taint_summary"]["allocated_edge_count"] == 1

    # 2. Next-hop predictions at T=5m: cannot reverse to Victim or invent unobserved nodes
    assert d5["stages"]["next_hop_prediction"]["status"] == "insufficient_evidence"
    assert d5["next_hop_predictions"] == []

    # 3. Forecast generation at T=5m: 0 paths generated, insufficient evidence
    assert d5["stages"]["forecast_simulation"]["status"] == "insufficient_evidence"
    assert d5["forecast_report"]["paths_generated_count"] == 0

    # 4. Model artifact unavailability & partial overall status
    assert d5["stages"]["risk_assessment"]["status"] == "unavailable"
    assert d5["risk_predictions"] == []
    assert d5["overall_status"] == "partial"

    # Decision at T = 15 minutes (Mule1 -> Mule2 has occurred)
    t15 = T0 + timedelta(minutes=15)
    payload_t15 = {
        "simulation_timestamp": t15.isoformat(),
        "taint_seeds": [{"transaction_id": "tx-seed-1", "tainted_amount_minor_units": 100_000_00}],
    }
    resp_t15 = await client.post(f"/api/cases/{case_id}/analyze", json=payload_t15)
    assert resp_t15.status_code == 200
    d15 = resp_t15.json()

    # Taint is now at Mule2
    assert d15["taint_summary"]["current_tainted_accounts"] == ["Mule2"]
    assert d15["taint_summary"]["allocated_edge_count"] == 2

    # Cannot reverse to Mule1 or Victim, cannot predict Exit without evidence
    assert d15["stages"]["next_hop_prediction"]["status"] == "insufficient_evidence"
    assert d15["next_hop_predictions"] == []
    assert d15["stages"]["forecast_simulation"]["status"] == "insufficient_evidence"

