"""
API integration tests for AEGIS-Flow backend.

Covers:
- Valid case creation
- Invalid case rejection (schema violations)
- Duplicate case_id handling
- Single event ingestion
- Batch event ingestion (order preservation)
- Timeline ordering by occurred_at
- Missing case handling (404)
- Invalid canonical event rejection
- Duplicate event_id handling
"""

from __future__ import annotations

import json
import copy

import pytest

from tests.backend.conftest import (
    VALID_CASE,
    VALID_EVENT_1,
    VALID_EVENT_2,
    VALID_EVENT_3,
)


# ═══════════════════════════════════════════════════════════════════════════════
# CASE TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateCase:
    """POST /api/cases"""

    @pytest.mark.asyncio
    async def test_valid_case_creation(self, client):
        resp = await client.post(
            "/api/cases", content=json.dumps(VALID_CASE)
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["case_id"] == "case-001"
        assert data["schema_version"] == "1.0.0"
        assert data["status"] == "open"

    @pytest.mark.asyncio
    async def test_case_with_description(self, client):
        payload = {**VALID_CASE, "description": "Test description"}
        resp = await client.post("/api/cases", content=json.dumps(payload))
        assert resp.status_code == 201
        assert resp.json()["description"] == "Test description"

    @pytest.mark.asyncio
    async def test_invalid_case_missing_required_field(self, client):
        """Missing 'title' should be rejected with 422."""
        payload = {k: v for k, v in VALID_CASE.items() if k != "title"}
        resp = await client.post("/api/cases", content=json.dumps(payload))
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_case_bad_origin_enum(self, client):
        payload = {**VALID_CASE, "origin": "not_a_valid_origin"}
        resp = await client.post("/api/cases", content=json.dumps(payload))
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_case_naive_timestamp(self, client):
        """Timestamps without timezone info should be rejected."""
        payload = {**VALID_CASE, "opened_at": "2026-10-08T15:00:00"}
        resp = await client.post("/api/cases", content=json.dumps(payload))
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_case_empty_case_id(self, client):
        payload = {**VALID_CASE, "case_id": ""}
        resp = await client.post("/api/cases", content=json.dumps(payload))
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_case_extra_field(self, client):
        """extra='forbid' should reject unknown fields."""
        payload = {**VALID_CASE, "risk_score": 0.95}
        resp = await client.post("/api/cases", content=json.dumps(payload))
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_duplicate_case_id_rejected(self, client):
        resp1 = await client.post("/api/cases", content=json.dumps(VALID_CASE))
        assert resp1.status_code == 201
        resp2 = await client.post("/api/cases", content=json.dumps(VALID_CASE))
        assert resp2.status_code == 409


class TestGetCase:
    """GET /api/cases/{case_id}"""

    @pytest.mark.asyncio
    async def test_get_existing_case(self, client):
        await client.post("/api/cases", content=json.dumps(VALID_CASE))
        resp = await client.get("/api/cases/case-001")
        assert resp.status_code == 200
        assert resp.json()["case_id"] == "case-001"

    @pytest.mark.asyncio
    async def test_get_missing_case_returns_404(self, client):
        resp = await client.get("/api/cases/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_all_cases(self, client):
        resp_initial = await client.get("/api/cases")
        assert resp_initial.status_code == 200
        assert isinstance(resp_initial.json(), list)

        await client.post("/api/cases", content=json.dumps(VALID_CASE))
        resp = await client.get("/api/cases")
        assert resp.status_code == 200
        cases = resp.json()
        assert len(cases) >= 1
        assert any(c["case_id"] == "case-001" for c in cases)


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestIngestEvent:
    """POST /api/events?case_id=..."""

    @pytest.mark.asyncio
    async def test_valid_single_event(self, client):
        # Create case first
        await client.post("/api/cases", content=json.dumps(VALID_CASE))
        resp = await client.post(
            "/api/events",
            params={"case_id": "case-001"},
            content=json.dumps(VALID_EVENT_1),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["event_id"] == "evt-001"
        assert data["amount_minor_units"] == 5000000

    @pytest.mark.asyncio
    async def test_event_without_case_returns_404(self, client):
        resp = await client.post(
            "/api/events",
            params={"case_id": "no-such-case"},
            content=json.dumps(VALID_EVENT_1),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_event_missing_field(self, client):
        await client.post("/api/cases", content=json.dumps(VALID_CASE))
        bad = {k: v for k, v in VALID_EVENT_1.items() if k != "sender"}
        resp = await client.post(
            "/api/events",
            params={"case_id": "case-001"},
            content=json.dumps(bad),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_event_bad_currency(self, client):
        await client.post("/api/cases", content=json.dumps(VALID_CASE))
        bad = {**VALID_EVENT_1, "currency": "inr"}  # must be uppercase
        resp = await client.post(
            "/api/events",
            params={"case_id": "case-001"},
            content=json.dumps(bad),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_duplicate_event_id_rejected(self, client):
        await client.post("/api/cases", content=json.dumps(VALID_CASE))
        await client.post(
            "/api/events",
            params={"case_id": "case-001"},
            content=json.dumps(VALID_EVENT_1),
        )
        resp = await client.post(
            "/api/events",
            params={"case_id": "case-001"},
            content=json.dumps(VALID_EVENT_1),
        )
        assert resp.status_code == 409


class TestIngestBatch:
    """POST /api/events/batch?case_id=..."""

    @pytest.mark.asyncio
    async def test_valid_batch(self, client):
        await client.post("/api/cases", content=json.dumps(VALID_CASE))
        batch = [VALID_EVENT_1, VALID_EVENT_2]
        resp = await client.post(
            "/api/events/batch",
            params={"case_id": "case-001"},
            content=json.dumps(batch),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["accepted"] == 2
        assert data["event_ids"] == ["evt-001", "evt-002"]

    @pytest.mark.asyncio
    async def test_batch_preserves_order(self, client):
        await client.post("/api/cases", content=json.dumps(VALID_CASE))
        batch = [VALID_EVENT_2, VALID_EVENT_1]  # reversed order
        resp = await client.post(
            "/api/events/batch",
            params={"case_id": "case-001"},
            content=json.dumps(batch),
        )
        assert resp.status_code == 201
        # event_ids should reflect submission order, not sorted order
        assert resp.json()["event_ids"] == ["evt-002", "evt-001"]

    @pytest.mark.asyncio
    async def test_batch_without_case_returns_404(self, client):
        resp = await client.post(
            "/api/events/batch",
            params={"case_id": "no-such-case"},
            content=json.dumps([VALID_EVENT_1]),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_batch_with_duplicate_event_id_in_batch(self, client):
        await client.post("/api/cases", content=json.dumps(VALID_CASE))
        batch = [VALID_EVENT_1, VALID_EVENT_1]
        resp = await client.post(
            "/api/events/batch",
            params={"case_id": "case-001"},
            content=json.dumps(batch),
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_batch_with_duplicate_against_existing(self, client):
        await client.post("/api/cases", content=json.dumps(VALID_CASE))
        # Ingest one event
        await client.post(
            "/api/events",
            params={"case_id": "case-001"},
            content=json.dumps(VALID_EVENT_1),
        )
        # Batch containing the same event_id
        batch = [VALID_EVENT_1, VALID_EVENT_2]
        resp = await client.post(
            "/api/events/batch",
            params={"case_id": "case-001"},
            content=json.dumps(batch),
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_batch_not_a_list(self, client):
        await client.post("/api/cases", content=json.dumps(VALID_CASE))
        resp = await client.post(
            "/api/events/batch",
            params={"case_id": "case-001"},
            content=json.dumps(VALID_EVENT_1),  # single object, not array
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_batch_invalid_event_reports_index(self, client):
        await client.post("/api/cases", content=json.dumps(VALID_CASE))
        bad_event = {**VALID_EVENT_2, "currency": "inr"}
        batch = [VALID_EVENT_1, bad_event]
        resp = await client.post(
            "/api/events/batch",
            params={"case_id": "case-001"},
            content=json.dumps(batch),
        )
        assert resp.status_code == 422
        assert "index 1" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════════
# TIMELINE TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestTimeline:
    """GET /api/cases/{case_id}/timeline"""

    @pytest.mark.asyncio
    async def test_timeline_ordered_by_occurred_at(self, client):
        await client.post("/api/cases", content=json.dumps(VALID_CASE))
        # Ingest events out of chronological order:
        # evt-003 occurred at 13:00, evt-001 at 14:30, evt-002 at 15:00
        batch = [VALID_EVENT_1, VALID_EVENT_2, VALID_EVENT_3]
        await client.post(
            "/api/events/batch",
            params={"case_id": "case-001"},
            content=json.dumps(batch),
        )
        resp = await client.get("/api/cases/case-001/timeline")
        assert resp.status_code == 200
        timeline = resp.json()
        assert len(timeline) == 3
        # Should be sorted by occurred_at ascending
        assert timeline[0]["event_id"] == "evt-003"  # 13:00
        assert timeline[1]["event_id"] == "evt-001"  # 14:30
        assert timeline[2]["event_id"] == "evt-002"  # 15:00

    @pytest.mark.asyncio
    async def test_timeline_empty_case(self, client):
        await client.post("/api/cases", content=json.dumps(VALID_CASE))
        resp = await client.get("/api/cases/case-001/timeline")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_timeline_missing_case_returns_404(self, client):
        resp = await client.get("/api/cases/nonexistent/timeline")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# GRAPH TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestGraph:
    """GET /api/cases/{case_id}/graph"""

    @pytest.mark.asyncio
    async def test_graph_returns_nodes_and_edges(self, client):
        await client.post("/api/cases", content=json.dumps(VALID_CASE))
        batch = [VALID_EVENT_1, VALID_EVENT_2]
        await client.post(
            "/api/events/batch",
            params={"case_id": "case-001"},
            content=json.dumps(batch),
        )
        resp = await client.get("/api/cases/case-001/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["case_id"] == "case-001"
        assert data["edge_count"] == 2
        # 3 unique accounts across 2 events
        assert data["node_count"] == 3

    @pytest.mark.asyncio
    async def test_graph_missing_case_returns_404(self, client):
        resp = await client.get("/api/cases/nonexistent/graph")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════════


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
